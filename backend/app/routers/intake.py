"""
intake.py
Staged-resources endpoints for the Requirements Intake Quality feature: a PM
assembles several resources (primary requirements, meeting notes, policy
references — PDF/.docx/image) per project before running extraction. See
backend/app/services/intake_resources.py for the persistence + eager
processing logic this router calls into, and requirements_extraction.py's
run_staged_extraction() (Phase 4) for how these eventually feed extraction.
"""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..db.models import Project
from ..db.session import get_db
from ..deps import get_openai_client
from ..schemas.intake import (
    ClarifyingQuestionOut,
    ClarifyingQuestionStatusUpdate,
    IntakeResourceKind,
    IntakeResourceOut,
)
from ..services.clarifying_questions import (
    generate_clarifying_questions_for_project,
    list_clarifying_questions,
    set_question_status,
)
from ..services.intake_resources import (
    SUFFIX_TO_FILE_TYPE,
    create_intake_resource,
    delete_intake_resource,
    list_intake_resources,
)

# db.session (imported above) already put the repo root on sys.path, so this
# resolves the same way config.py does everywhere else in the app.
from config import EXTRACTION_MODEL  # noqa: E402

router = APIRouter(prefix="/projects/{project_id}/resources", tags=["intake"])
questions_router = APIRouter(prefix="/projects/{project_id}/clarifying-questions", tags=["intake"])


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


async def _save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUFFIX_TO_FILE_TYPE:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix} (expected .pdf, .docx, or an image)",
        )
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / file.filename
    tmp_path.write_bytes(await file.read())
    return tmp_path


@router.post("", response_model=IntakeResourceOut, status_code=201)
async def upload_intake_resource(
    project_id: str,
    file: UploadFile = File(...),
    resource_kind: IntakeResourceKind = Form(...),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
    llm_client=Depends(get_openai_client),
):
    """
    Stage one resource and process it immediately (text extraction for
    PDF/.docx, GPT-4o vision transcription for an image) so the PM can
    verify what was understood before running extraction. A processing
    failure is recorded on the resource (processing_error) rather than
    failing this request — one bad file shouldn't block staging the rest.
    """
    _get_project_or_404(db, project_id)
    tmp_path = await _save_upload(file)

    try:
        resource = create_intake_resource(
            session=db,
            project_id=project_id,
            resource_kind=resource_kind,
            file_path=tmp_path,
            original_filename=file.filename,
            llm_client=llm_client,
            notes=notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    db.refresh(resource)
    return resource


@router.get("", response_model=list[IntakeResourceOut])
def get_intake_resources(project_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    return list_intake_resources(db, project_id)


@router.delete("/{resource_id}", status_code=204)
def remove_intake_resource(project_id: str, resource_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    try:
        delete_intake_resource(db, project_id, resource_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@questions_router.post("", response_model=list[ClarifyingQuestionOut], status_code=201)
def generate_clarifying_questions_endpoint(
    project_id: str, db: Session = Depends(get_db), llm_client=Depends(get_openai_client)
):
    """
    Reads every staged resource with successfully extracted text and
    proposes plain-language questions for the PM to relay to the client.
    Advisory only — never required before running extraction.
    """
    _get_project_or_404(db, project_id)
    try:
        questions = generate_clarifying_questions_for_project(db, project_id, llm_client, model=EXTRACTION_MODEL)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    for q in questions:
        db.refresh(q)
    return questions


@questions_router.get("", response_model=list[ClarifyingQuestionOut])
def get_clarifying_questions(project_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    return list_clarifying_questions(db, project_id)


@questions_router.patch("/{question_id}", response_model=ClarifyingQuestionOut)
def update_clarifying_question(
    project_id: str, question_id: str, body: ClarifyingQuestionStatusUpdate, db: Session = Depends(get_db)
):
    _get_project_or_404(db, project_id)
    try:
        question = set_question_status(db, project_id, question_id, body.status, body.answer_text)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    db.refresh(question)
    return question
