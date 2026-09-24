"""
requirements.py
Requirements & Discovery module endpoints: upload+extract (fresh SOW or
change request), review, edit, approve, gap resolution. See
backend/app/services/{text_ingestion,requirements_extraction,
requirements_review}.py for the logic this router calls into.
"""

import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from ..db.models import Document, EvaluationReport, Gap, Project, RequirementItem
from ..db.session import get_db
from ..deps import get_confluence_client, get_openai_client
from ..schemas.requirements import (
    AcDraftOut,
    ChangeRequestIngestResponse,
    ConfluencePublishResponse,
    CrRequestType,
    DocumentOut,
    EpicDraftOut,
    ErrorHandlingIO,
    GapResolveAsStory,
    GapStatusUpdate,
    ItemCreate,
    ItemDraftRequest,
    ItemUpdate,
    RequirementsDetail,
    ScenarioIO,
    StoryDraftOut,
    TextIngestResponse,
)
from ..services import confluence_export
from ..services import requirements_review as review
from ..services.confluence_client import ConfluenceError
from ..services.business_document import build_business_document
from ..services.pdf_export import generate_business_pdf, generate_requirements_pdf
from ..services.requirements_evaluation import run_evaluation
from ..services.requirements_extraction import (
    generate_item_draft_for_document,
    run_change_request_extraction,
    run_extraction,
    run_staged_extraction,
    run_suggestions_background,
)
from ..services.text_ingestion import create_text_document

# db.session (imported above) already put the repo root on sys.path, so this
# resolves the same way config.py does everywhere else in the app.
from config import EXTRACTION_MODEL  # noqa: E402

router = APIRouter(prefix="/projects/{project_id}/requirements", tags=["requirements"])

_ALLOWED_SUFFIXES = {".pdf", ".docx"}

# Threads spawned by _spawn_suggestions_thread, kept only so tests can wait
# for them deterministically (see _join_suggestion_threads_for_tests) rather
# than polling the API with an arbitrary sleep loop. Never read otherwise.
_suggestion_threads: list[threading.Thread] = []


def _spawn_suggestions_thread(document_id: str, llm_client) -> None:
    """
    Suggestions run on a genuinely independent daemon thread, not FastAPI's
    BackgroundTasks. Confirmed directly (a hung test plus a faulthandler
    stack dump) that BackgroundTasks run BEFORE a yield-dependency's post-
    yield cleanup finishes, not after — so a background task trying to
    acquire the same single-writer _write_lock (db/session.py) the still-
    open request session is holding deadlocks every time, deterministically.
    A plain thread is decoupled from that sequencing entirely: it may
    briefly wait for the lock if the original request hasn't finished yet,
    which is normal serialization, not a deadlock, since the original
    request's own dependency cleanup proceeds on its own schedule,
    unblocked by anything this thread does.
    """
    thread = threading.Thread(
        target=run_suggestions_background, args=(document_id, llm_client, EXTRACTION_MODEL), daemon=True
    )
    _suggestion_threads.append(thread)
    thread.start()


def _join_suggestion_threads_for_tests(timeout: float = 30) -> None:
    """
    Test-only synchronization point — waits for every suggestions thread
    spawned so far to finish, so a test can assert on suggestions
    deterministically right after an upload call returns, instead of an
    arbitrary sleep/poll loop. Not used by the app itself.
    """
    while _suggestion_threads:
        _suggestion_threads.pop().join(timeout=timeout)


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


def _get_requirement_doc_or_404(db: Session, project_id: str, doc_id: str) -> Document:
    doc = (
        db.query(Document)
        .filter(
            Document.id == doc_id,
            Document.project_id == project_id,
            Document.doc_type == "requirement",
        )
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Requirement document {doc_id} not found")
    return doc


def _get_change_request_doc_or_404(db: Session, project_id: str, doc_id: str) -> Document:
    doc = (
        db.query(Document)
        .filter(
            Document.id == doc_id,
            Document.project_id == project_id,
            Document.doc_type == "change_request",
        )
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Change request document {doc_id} not found")
    return doc


def _ordered_items_query(db: Session, document_id: str):
    """
    Every epic/story query in this router goes through here so the PM
    always sees items in E1, E2, E3... / S1, S2, S3... order — never the
    order an unordered query happens to return, which SQLite was
    satisfying via the (document_id, external_id) unique index and
    therefore sorting external_id as a STRING ("E10" before "E2"). Casting
    the numeric suffix out of external_id sorts correctly regardless of
    digit count or insertion timing, and is robust to a batch insert where
    several rows could plausibly land on the same created_at timestamp.
    """
    return (
        db.query(RequirementItem)
        .filter(RequirementItem.document_id == document_id)
        .order_by(cast(func.substr(RequirementItem.external_id, 2), Integer))
    )


def _detail_for(db: Session, doc: Document) -> RequirementsDetail:
    items = _ordered_items_query(db, doc.id).all()
    gaps = db.query(Gap).filter(Gap.document_id == doc.id).all()
    # A pending suggestion isn't real content yet — keep it out of the main
    # tree until the PM accepts it (dismissed ones stay hidden for good,
    # same as a dismissed gap). Everything else (extracted, pm_manual,
    # pm_ai_assisted, and accepted suggestions) is part of the real tree.
    visible = [i for i in items if i.suggestion_status in (None, "accepted")]
    pending = [i for i in items if i.suggestion_status == "pending"]
    evaluation = db.query(EvaluationReport).filter(EvaluationReport.document_id == doc.id).first()
    return RequirementsDetail(
        document=doc,
        epics=[i for i in visible if i.type == "epic"],
        stories=[i for i in visible if i.type == "story"],
        gaps=gaps,
        unresolved_gap_count=sum(1 for g in gaps if g.status == "open"),
        suggestions=pending,
        evaluation=evaluation,
    )


async def _save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix} (expected .pdf or .docx)")
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / file.filename
    tmp_path.write_bytes(await file.read())
    return tmp_path


@router.post("", response_model=TextIngestResponse, status_code=201)
async def upload_requirements(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    llm_client=Depends(get_openai_client),
):
    """
    Upload a fresh requirement doc (new-project SOW) and run extraction.
    Suggestions generation is spawned on its own thread (see
    _spawn_suggestions_thread / run_suggestions_background) rather than run
    inline — it's advisory bonus content, not the primary deliverable, and
    was a meaningful chunk of upload latency for a call the PM is never
    blocked on needing.
    """
    _get_project_or_404(db, project_id)
    tmp_path = await _save_upload(file)

    try:
        doc = create_text_document(
            session=db,
            project_id=project_id,
            doc_type="requirement",
            file_path=tmp_path,
            original_filename=file.filename,
        )
        _, epics, stories, gaps = run_extraction(db, doc, llm_client, model=EXTRACTION_MODEL)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        # _call_llm/_call_with_tool already retry a malformed model response
        # a few times on their own — reaching here means that was exhausted,
        # or some other unexpected failure occurred. Surface a clean,
        # actionable message rather than a raw 500 with no detail.
        raise HTTPException(
            status_code=502,
            detail=f"Extraction failed unexpectedly ({e}). This is sometimes a transient AI response "
            "issue — please try uploading again.",
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    db.flush()
    _spawn_suggestions_thread(doc.id, llm_client)
    return TextIngestResponse(document=doc, epics_extracted=epics, stories_extracted=stories, gaps_found=gaps)


@router.post("/run-staged-extraction", response_model=TextIngestResponse, status_code=201)
def run_staged_extraction_endpoint(
    project_id: str, db: Session = Depends(get_db), llm_client=Depends(get_openai_client)
):
    """
    Initial extraction (creating v1 of this project's requirements) from
    everything staged via the Requirements Intake Quality feature — see
    services/intake_resources.py, clarifying_questions.py,
    standing_policies.py, and run_staged_extraction()'s own docstring.
    """
    project = _get_project_or_404(db, project_id)

    try:
        doc, epics, stories, gaps = run_staged_extraction(db, project, llm_client, model=EXTRACTION_MODEL)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Extraction failed unexpectedly ({e}). This is sometimes a transient AI response "
            "issue — please try running extraction again.",
        )

    db.flush()
    _spawn_suggestions_thread(doc.id, llm_client)
    return TextIngestResponse(document=doc, epics_extracted=epics, stories_extracted=stories, gaps_found=gaps)


@router.post("/change-requests", response_model=ChangeRequestIngestResponse, status_code=201)
async def upload_change_request(
    project_id: str,
    file: UploadFile = File(...),
    request_type: CrRequestType = Form(...),
    classification: Optional[str] = Form(None),
    estimated_effort: Optional[str] = Form(None),
    estimated_cost: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    llm_client=Depends(get_openai_client),
):
    """
    Upload a Change Request against this project's latest approved
    requirements version. Extraction is context-aware against that baseline;
    its results are merged into a new requirements version rather than left
    as a disconnected document — see run_change_request_extraction().
    """
    _get_project_or_404(db, project_id)

    approved = review.get_latest_approved_requirements(db, project_id)
    if approved is None:
        raise HTTPException(
            status_code=409,
            detail="This project has no approved requirements version yet — "
            "change requests can only be filed against an approved baseline.",
        )

    tmp_path = await _save_upload(file)

    try:
        cr_doc = create_text_document(
            session=db,
            project_id=project_id,
            doc_type="change_request",
            file_path=tmp_path,
            original_filename=file.filename,
            checked_against_document_id=approved.id,
            type_metadata={
                "request_type": request_type,
                "classification": classification,
                "estimated_effort": estimated_effort,
                "estimated_cost": estimated_cost,
            },
        )
        new_version, epics, stories, gaps = run_change_request_extraction(
            db, cr_doc, approved, llm_client, model=EXTRACTION_MODEL
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        # _call_llm/_call_with_tool already retry a malformed model response
        # a few times on their own — reaching here means that was exhausted,
        # or some other unexpected failure occurred. Surface a clean,
        # actionable message rather than a raw 500 with no detail.
        raise HTTPException(
            status_code=502,
            detail=f"Change request extraction failed unexpectedly ({e}). This is sometimes a "
            "transient AI response issue — please try filing it again.",
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    db.flush()
    _spawn_suggestions_thread(new_version.id, llm_client)
    return ChangeRequestIngestResponse(
        change_request_document=cr_doc,
        requirements_document=new_version,
        epics_extracted=epics,
        stories_extracted=stories,
        gaps_found=gaps,
    )


@router.get("", response_model=RequirementsDetail)
def get_latest_requirements(project_id: str, db: Session = Depends(get_db)):
    """The current (highest-version) requirements document for this project."""
    _get_project_or_404(db, project_id)
    doc = (
        db.query(Document)
        .filter(Document.project_id == project_id, Document.doc_type == "requirement")
        .order_by(Document.version.desc())
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="No requirements document uploaded yet")
    return _detail_for(db, doc)


@router.get("/change-requests", response_model=list[DocumentOut])
def list_change_requests(project_id: str, db: Session = Depends(get_db)):
    """All change requests filed against this project, newest first."""
    _get_project_or_404(db, project_id)
    return (
        db.query(Document)
        .filter(Document.project_id == project_id, Document.doc_type == "change_request")
        .order_by(Document.version.desc())
        .all()
    )


@router.get("/change-requests/{cr_doc_id}", response_model=DocumentOut)
def get_change_request(project_id: str, cr_doc_id: str, db: Session = Depends(get_db)):
    """
    A single change request's own record — source file, Request Type/
    Classification/Effort/Cost (type_metadata), and which baseline it was
    checked against (checked_against_document_id) and requirements version it
    produced (type_metadata.produced_requirements_document_id).
    """
    return _get_change_request_doc_or_404(db, project_id, cr_doc_id)


@router.get("/{doc_id}", response_model=RequirementsDetail)
def get_requirements_version(project_id: str, doc_id: str, db: Session = Depends(get_db)):
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    return _detail_for(db, doc)


@router.post("/{doc_id}/items", response_model=RequirementsDetail, status_code=201)
def create_requirement_item(
    project_id: str,
    doc_id: str,
    body: ItemCreate,
    db: Session = Depends(get_db),
):
    """
    Manually add an epic or story the extraction missed — or confirm one
    the PM drafted with AI-assisted generation first (POST
    .../items/generate-draft), in which case body.origin is
    "pm_ai_assisted" instead of the default "pm_manual".
    """
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        target_doc, _item = review.create_item(
            db,
            doc,
            item_type=body.type,
            text=body.text,
            parent_id=body.parent_id,
            description=body.description,
            scenarios=[s.model_dump() for s in body.scenarios] if body.scenarios is not None else None,
            acceptance_criteria=[a.model_dump() for a in body.acceptance_criteria]
            if body.acceptance_criteria is not None
            else None,
            error_handling=[e.model_dump() for e in body.error_handling]
            if body.error_handling is not None
            else None,
            assumptions=body.assumptions,
            dependencies=body.dependencies,
            source_reference=body.source_reference,
            origin=body.origin or "pm_manual",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.flush()
    return _detail_for(db, target_doc)


@router.post("/{doc_id}/items/generate-draft")
def generate_draft(
    project_id: str,
    doc_id: str,
    body: ItemDraftRequest,
    db: Session = Depends(get_db),
    llm_client=Depends(get_openai_client),
):
    """
    AI-assisted item generation: the PM names a subject, the AI drafts the
    rest to the same structure as the extraction. Returns the draft only —
    nothing is persisted; the PM reviews it and confirms via the existing
    POST .../items (origin="pm_ai_assisted") for an epic/story, or PATCHes
    the target story's acceptance_criteria/scenarios/error_handling for
    those three kinds, since none of them is its own row. Pass
    body.previous_draft (this endpoint's own prior response for the same
    subject) when the PM clicked Regenerate rather than confirming.
    """
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        draft, _usage = generate_item_draft_for_document(
            db,
            doc,
            kind=body.kind,
            subject=body.subject,
            client=llm_client,
            model=EXTRACTION_MODEL,
            parent_id=body.parent_id,
            previous_draft=body.previous_draft,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.flush()

    if body.kind == "epic":
        return EpicDraftOut(**draft)
    if body.kind == "story":
        return StoryDraftOut(**draft)
    if body.kind == "acceptance_criterion":
        return AcDraftOut(**draft)
    if body.kind == "scenario":
        return ScenarioIO(**draft)
    return ErrorHandlingIO(**draft)


@router.patch("/{doc_id}/items/{item_id}", response_model=RequirementsDetail)
def update_item(
    project_id: str,
    doc_id: str,
    item_id: str,
    body: ItemUpdate,
    db: Session = Depends(get_db),
):
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        target_doc, _item = review.edit_item(
            db,
            doc,
            item_id,
            text=body.text,
            description=body.description,
            scenarios=[s.model_dump() for s in body.scenarios] if body.scenarios is not None else None,
            acceptance_criteria=[a.model_dump() for a in body.acceptance_criteria]
            if body.acceptance_criteria is not None
            else None,
            error_handling=[e.model_dump() for e in body.error_handling]
            if body.error_handling is not None
            else None,
            assumptions=body.assumptions,
            dependencies=body.dependencies,
            source_reference=body.source_reference,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    db.flush()
    return _detail_for(db, target_doc)


@router.delete("/{doc_id}/items/{item_id}", response_model=RequirementsDetail)
def delete_requirement_item(
    project_id: str,
    doc_id: str,
    item_id: str,
    db: Session = Depends(get_db),
):
    """Deletes a story, or an epic and every story under it together."""
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        target_doc = review.delete_item(db, doc, item_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    db.flush()
    return _detail_for(db, target_doc)


@router.patch("/{doc_id}/gaps/{gap_id}", response_model=RequirementsDetail)
def update_gap_status(
    project_id: str,
    doc_id: str,
    gap_id: str,
    body: GapStatusUpdate,
    db: Session = Depends(get_db),
):
    """Dismiss (ignore) or reopen a gap. Resolving into a story is a separate endpoint."""
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        review.set_gap_status(db, doc.id, gap_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.flush()
    return _detail_for(db, doc)


@router.post("/{doc_id}/gaps/{gap_id}/resolve-as-story", response_model=RequirementsDetail)
def resolve_gap_as_story(
    project_id: str,
    doc_id: str,
    gap_id: str,
    body: GapResolveAsStory,
    db: Session = Depends(get_db),
):
    """
    Convert a gap into a real story under an existing epic — a bare title
    (origin="pm_manual", the default) unless the caller confirmed an
    AI-generated draft first (POST .../items/generate-draft with the gap's
    own description as the subject), in which case body.origin is
    "pm_ai_assisted" and scenarios/acceptance_criteria/error_handling carry
    the full draft.
    """
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        target_doc, _item, _gap = review.resolve_gap_as_story(
            db,
            doc,
            gap_id,
            parent_id=body.parent_id,
            text=body.text,
            description=body.description,
            scenarios=[s.model_dump() for s in body.scenarios] if body.scenarios is not None else None,
            acceptance_criteria=[a.model_dump() for a in body.acceptance_criteria]
            if body.acceptance_criteria is not None
            else None,
            error_handling=[e.model_dump() for e in body.error_handling]
            if body.error_handling is not None
            else None,
            origin=body.origin or "pm_manual",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.flush()
    return _detail_for(db, target_doc)


@router.post("/{doc_id}/suggestions/{item_id}/accept", response_model=RequirementsDetail)
def accept_suggestion(project_id: str, doc_id: str, item_id: str, db: Session = Depends(get_db)):
    """Promotes a pending AI suggestion into the real epic/story tree."""
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        target_doc, _item = review.accept_suggestion(db, doc, item_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    db.flush()
    return _detail_for(db, target_doc)


@router.post("/{doc_id}/suggestions/{item_id}/dismiss", response_model=RequirementsDetail)
def dismiss_suggestion(project_id: str, doc_id: str, item_id: str, db: Session = Depends(get_db)):
    """Dismisses a pending AI suggestion — kept on record, hidden from every view."""
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        target_doc, _item = review.dismiss_suggestion(db, doc, item_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    db.flush()
    return _detail_for(db, target_doc)


def _export_content(db: Session, doc: Document):
    """Epics, stories and gaps for an export — the same visible tree the PM
    reviewed and approved: pending/dismissed AI suggestions are excluded,
    exactly as _detail_for() keeps them out of the review screen."""
    items = [i for i in _ordered_items_query(db, doc.id).all() if i.suggestion_status in (None, "accepted")]
    gaps = db.query(Gap).filter(Gap.document_id == doc.id).all()
    return [i for i in items if i.type == "epic"], [i for i in items if i.type == "story"], gaps


def _version_chain(db: Session, doc: Document) -> list[Document]:
    """Every version up to and including `doc`, oldest first."""
    chain = [doc]
    while chain[0].previous_version_id:
        previous = db.query(Document).filter(Document.id == chain[0].previous_version_id).first()
        if previous is None:
            break
        chain.insert(0, previous)
    return chain


def _business_document_for(db: Session, project: Project, doc: Document):
    epics, stories, gaps = _export_content(db, doc)
    return build_business_document(project, doc, epics, stories, gaps, _version_chain(db, doc))


@router.get("/{doc_id}/export.pdf")
def export_requirements_pdf(
    project_id: str,
    doc_id: str,
    format: Literal["business", "delivery"] = Query(
        "business",
        description="'business': stakeholder-facing business requirements document (default). "
        "'delivery': epics/stories with scenarios and error handling, for the delivery team.",
    ),
    db: Session = Depends(get_db),
):
    """
    A clean PDF of an approved version. Generated fresh on every request
    rather than cached at approval time, so it always reflects the current
    gap-resolution state.
    """
    project = _get_project_or_404(db, project_id)
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    if doc.approval_status != "approved":
        raise HTTPException(
            status_code=400,
            detail="Only approved requirement versions can be exported to PDF.",
        )

    safe_name = project.name.replace(" ", "_")
    if format == "business":
        pdf_bytes = generate_business_pdf(_business_document_for(db, project, doc))
        filename = f"{safe_name}_business_requirements_v{doc.version}.pdf"
    else:
        epics, stories, gaps = _export_content(db, doc)
        pdf_bytes = generate_requirements_pdf(project, doc, epics, stories, gaps)
        filename = f"{safe_name}_delivery_requirements_v{doc.version}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{doc_id}/publish-confluence", response_model=ConfluencePublishResponse)
def publish_confluence(
    project_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    confluence_client=Depends(get_confluence_client),
):
    """
    Publishes an approved version as its own Confluence page — a manual,
    explicit action (never automatic on approval), since sharing something
    externally to stakeholders is a bigger step than an internal signoff.
    One page per approved version, never overwritten: editing after
    approval and re-approving publishes again as a brand-new page, linked
    from its predecessor in both directions.
    """
    project = _get_project_or_404(db, project_id)
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    if doc.approval_status != "approved":
        raise HTTPException(
            status_code=400,
            detail="Only approved requirement versions can be published to Confluence.",
        )

    existing = (doc.type_metadata or {}).get("confluence")
    if existing:
        return ConfluencePublishResponse(document=doc, page_id=existing["page_id"], page_url=existing["page_url"])

    previous_doc = (
        db.query(Document).filter(Document.id == doc.previous_version_id).first()
        if doc.previous_version_id
        else None
    )

    try:
        result = confluence_export.publish_requirements_version(
            db, confluence_client, project, previous_doc, _business_document_for(db, project, doc)
        )
    except ConfluenceError as e:
        raise HTTPException(status_code=502, detail=f"Confluence publish failed: {e.detail}")

    doc.type_metadata = {
        **(doc.type_metadata or {}),
        "confluence": {
            "page_id": result["page_id"],
            "page_url": result["page_url"],
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    db.flush()
    db.refresh(doc)
    return ConfluencePublishResponse(document=doc, page_id=result["page_id"], page_url=result["page_url"])


@router.post("/{doc_id}/approve", response_model=DocumentOut)
def approve(project_id: str, doc_id: str, db: Session = Depends(get_db)):
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        review.approve_document(db, doc)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.flush()
    db.refresh(doc)
    return doc


@router.post("/{doc_id}/evaluate", response_model=RequirementsDetail)
def evaluate_requirements(
    project_id: str, doc_id: str, db: Session = Depends(get_db), llm_client=Depends(get_openai_client)
):
    """
    Runs (or re-runs) the on-demand quality evaluation for this document's
    CURRENT visible tree — see services/requirements_evaluation.py::
    run_evaluation(). Always an explicit PM action, never automatic.
    """
    doc = _get_requirement_doc_or_404(db, project_id, doc_id)
    try:
        run_evaluation(db, doc, llm_client, model=EXTRACTION_MODEL)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Evaluation failed unexpectedly ({e}). This is sometimes a transient AI response "
            "issue — please try running the evaluation again.",
        )
    db.flush()
    return _detail_for(db, doc)
