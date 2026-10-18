"""
Development stories: the project's tech profile, development stories planned
from approved user stories, technical tasks and their coding prompts. See
services/dev_stories.py. Nothing here writes to Jira.
"""

import anthropic
from botocore.exceptions import BotoCoreError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ai.text.coding_prompt_generator import CodingPromptError

from ..db.models import Project
from ..db.session import get_db
from ..deps import get_coding_llm_client, get_openai_client
from ..schemas.dev_stories import (
    DevOverviewOut,
    DevStoryOut,
    DevStoryUpdate,
    DevTaskOut,
    DevTaskUpdate,
    TechDocumentRead,
    TechProfileIn,
    TechProfileOut,
)
from ..services import dev_stories as svc

router = APIRouter(prefix="/projects/{project_id}/dev-stories", tags=["dev-stories"])

_MAX_TECH_DOCUMENT_BYTES = 10 * 1024 * 1024


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


@router.get("", response_model=DevOverviewOut)
def get_overview(project_id: str, db: Session = Depends(get_db)):
    """The latest approved version's epics (dependency order) with their user
    stories and planned development stories, plus the tech profile."""
    return svc.overview(db, _get_project_or_404(db, project_id))


@router.get("/tech-profile", response_model=TechProfileOut)
def get_tech_profile(project_id: str, db: Session = Depends(get_db)):
    return svc.get_tech_profile(_get_project_or_404(db, project_id))


@router.put("/tech-profile", response_model=TechProfileOut)
def save_tech_profile(project_id: str, body: TechProfileIn, db: Session = Depends(get_db)):
    return svc.save_tech_profile(db, _get_project_or_404(db, project_id), body.areas)


@router.post("/tech-profile/document", response_model=TechDocumentRead)
async def read_tech_document(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    llm_client=Depends(get_openai_client),
):
    """Reads an uploaded tech-stack document. Its text is kept for the coding
    prompts; the areas it specifies come back merged into the empty fields,
    unsaved, for the person to review."""
    project = _get_project_or_404(db, project_id)
    data = await file.read()
    if len(data) > _MAX_TECH_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="The document is larger than 10 MB.")
    try:
        return svc.read_tech_document(db, project, file.filename or "document", data, llm_client)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/epics/{epic_external_id}/generate", response_model=list[DevStoryOut])
def generate_for_epic(
    project_id: str, epic_external_id: str, db: Session = Depends(get_db), llm_client=Depends(get_openai_client)
):
    """Plans (or re-plans) one epic's development stories and technical tasks
    from the latest approved version. One epic per request: the page calls it
    for each selected epic, so a long batch never runs as one request."""
    project = _get_project_or_404(db, project_id)
    try:
        svc.generate_for_epic(db, project, epic_external_id, llm_client)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    epic = next((e for e in svc.overview(db, project)["epics"] if e["external_id"] == epic_external_id), None)
    return epic["dev_stories"] if epic else []


@router.patch("/stories/{story_id}", response_model=DevStoryOut)
def update_story(project_id: str, story_id: str, body: DevStoryUpdate, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    try:
        return svc.update_story(db, project, story_id, body.model_dump(exclude_unset=True))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/stories/{story_id}", status_code=204)
def delete_story(project_id: str, story_id: str, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    try:
        svc.delete_story(db, project, story_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/tasks/{task_id}", response_model=DevTaskOut)
def update_task(project_id: str, task_id: str, body: DevTaskUpdate, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    try:
        return svc.update_task(db, project, task_id, body.model_dump(exclude_unset=True))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(project_id: str, task_id: str, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    try:
        svc.delete_task(db, project, task_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/tasks/{task_id}/coding-prompt", response_model=DevTaskOut)
def write_coding_prompt(
    project_id: str, task_id: str, db: Session = Depends(get_db), coding_client=Depends(get_coding_llm_client)
):
    """(Re)writes the task's coding prompt with the coding model (Claude on
    Bedrock). Replaces earlier edits; the page confirms before regenerating."""
    project = _get_project_or_404(db, project_id)
    try:
        task = svc.write_coding_prompt(db, project, task_id, coding_client)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CodingPromptError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except anthropic.APIError as e:  # Bedrock/model unreachable or access not granted: the old prompt stays
        raise HTTPException(status_code=502, detail=f"The coding model could not be reached: {e}")
    except BotoCoreError as e:  # no usable AWS credentials (e.g. an expired local SSO login)
        raise HTTPException(status_code=502, detail=f"The coding model could not be reached: AWS credentials failed ({e}).")
    return svc.task_out(task)
