"""
designs.py
Design review module endpoints: upload screens against an approved
requirements version, view per-screen alignment findings, resolve/dismiss
individual findings. See backend/app/services/design_alignment.py for the
logic this router calls into.
"""

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ai.ingest.ingest import tiles_for_document

from ..db.models import AlignmentFinding, AlignmentReport, Document, Project, RequirementItem
from ..db.session import get_db
from ..deps import get_embed_client, get_openai_client
from ..schemas.designs import (
    AlignmentFindingOut,
    AlignmentReportOut,
    DesignDetail,
    DesignIngestResponse,
    FindingStatusUpdate,
)
from ..services import design_alignment
from ..services import requirements_review as req_review
from ..services.ingestion import ingest_document

from config import ALIGNMENT_MODEL  # noqa: E402

router = APIRouter(prefix="/projects/{project_id}/designs", tags=["designs"])

_ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


def _get_design_doc_or_404(db: Session, project_id: str, doc_id: str) -> Document:
    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.project_id == project_id, Document.doc_type == "design")
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Design document {doc_id} not found")
    return doc


def _detail_for(db: Session, doc: Document) -> DesignDetail:
    reports = (
        db.query(AlignmentReport)
        .filter(AlignmentReport.design_document_id == doc.id)
        .order_by(AlignmentReport.page)
        .all()
    )
    report_ids = [r.id for r in reports]
    findings = (
        db.query(AlignmentFinding)
        .filter(AlignmentFinding.alignment_report_id.in_(report_ids))
        .all()
        if report_ids
        else []
    )
    findings_by_report: dict[str, list[AlignmentFinding]] = {}
    for f in findings:
        findings_by_report.setdefault(f.alignment_report_id, []).append(f)

    item_ids = {f.requirement_item_id for f in findings if f.requirement_item_id}
    external_id_by_item_id = {
        item.id: item.external_id
        for item in (
            db.query(RequirementItem).filter(RequirementItem.id.in_(item_ids)).all() if item_ids else []
        )
    }

    report_outs = []
    for r in reports:
        finding_outs = [
            AlignmentFindingOut(
                id=f.id,
                requirement_item_id=f.requirement_item_id,
                requirement_external_id=external_id_by_item_id.get(f.requirement_item_id),
                issue=f.issue,
                recommendation=f.recommendation,
                bounding_box=f.bounding_box,
                resolution_status=f.resolution_status,
            )
            for f in findings_by_report.get(r.id, [])
        ]
        report_outs.append(
            AlignmentReportOut(id=r.id, page=r.page, status=r.status, findings=finding_outs)
        )

    return DesignDetail(
        document=doc,
        requirements_document_id=doc.checked_against_document_id,
        reports=report_outs,
    )


@router.post("", response_model=DesignIngestResponse, status_code=201)
async def upload_design(
    project_id: str,
    file: UploadFile = File(...),
    requirements_document_id: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    embed_client=Depends(get_embed_client),
    openai_client=Depends(get_openai_client),
):
    """
    Upload a design screen export, checked against an approved requirements
    version — either the one you pass explicitly, or the project's latest
    approved version if you don't.
    """
    _get_project_or_404(db, project_id)

    if requirements_document_id:
        requirements_doc = (
            db.query(Document)
            .filter(
                Document.id == requirements_document_id,
                Document.project_id == project_id,
                Document.doc_type == "requirement",
                Document.approval_status == "approved",
            )
            .first()
        )
        if requirements_doc is None:
            raise HTTPException(
                status_code=400,
                detail=f"{requirements_document_id} is not an approved requirements document for this project",
            )
    else:
        requirements_doc = req_review.get_latest_approved_requirements(db, project_id)
        if requirements_doc is None:
            raise HTTPException(
                status_code=409,
                detail="No approved requirements version exists yet for this project — "
                "approve one before uploading designs against it.",
            )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / file.filename
    tmp_path.write_bytes(await file.read())

    try:
        doc, pages_indexed = ingest_document(
            session=db,
            project_id=project_id,
            doc_type="design",
            file_path=tmp_path,
            original_filename=file.filename,
            client=embed_client,
            checked_against_document_id=requirements_doc.id,
        )
        reports = design_alignment.run_alignment_check(
            db, doc, requirements_doc, openai_client, model=ALIGNMENT_MODEL
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Alignment check failed unexpectedly ({e}). This is sometimes a transient AI "
            "response issue — please try uploading again.",
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    db.flush()
    return DesignIngestResponse(
        document=doc,
        pages_indexed=pages_indexed,
        screens_checked=len(reports),
        aligned_count=sum(1 for r in reports if r.status == "aligned"),
        partial_count=sum(1 for r in reports if r.status == "partial"),
        misaligned_count=sum(1 for r in reports if r.status == "misaligned"),
    )


@router.get("", response_model=DesignDetail)
def get_latest_design(project_id: str, db: Session = Depends(get_db)):
    """The most recently uploaded design document's alignment detail."""
    _get_project_or_404(db, project_id)
    doc = (
        db.query(Document)
        .filter(Document.project_id == project_id, Document.doc_type == "design")
        .order_by(Document.uploaded_at.desc())
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="No design screens uploaded yet")
    return _detail_for(db, doc)


@router.get("/{doc_id}/screens/{page}/image")
def get_screen_image(project_id: str, doc_id: str, page: int, db: Session = Depends(get_db)):
    doc = _get_design_doc_or_404(db, project_id, doc_id)
    tile = next((t for t in tiles_for_document(doc.id) if t["page"] == page), None)
    if tile is None or not Path(tile["tile_path"]).exists():
        raise HTTPException(status_code=404, detail=f"No image for page {page} of document {doc_id}")
    return FileResponse(tile["tile_path"], media_type="image/png")


@router.get("/{doc_id}/alignment", response_model=DesignDetail)
def get_design_alignment(project_id: str, doc_id: str, db: Session = Depends(get_db)):
    doc = _get_design_doc_or_404(db, project_id, doc_id)
    return _detail_for(db, doc)


@router.patch("/{doc_id}/findings/{finding_id}", response_model=DesignDetail)
def update_finding_status(
    project_id: str,
    doc_id: str,
    finding_id: str,
    body: FindingStatusUpdate,
    db: Session = Depends(get_db),
):
    doc = _get_design_doc_or_404(db, project_id, doc_id)
    try:
        design_alignment.set_finding_status(db, doc.id, finding_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.flush()
    return _detail_for(db, doc)
