"""
ux_prompts.py
UI/UX Prompts endpoints: turn an approved requirements version's epics and
stories into Figma Make prompts. See services/ux_prompts.py for the logic and
ai/text/ux_prompt_generator.py for the prompt itself. Advisory only — every
generation is an explicit PM action and nothing is sent to Figma.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..db.models import Project
from ..db.session import get_db
from ..deps import get_openai_client
from ..schemas.ux_prompts import (
    StyleBriefIO,
    UxPromptEditUpdate,
    UxPromptMode,
    UxPromptOut,
    UxPromptSources,
)
from ..services import ux_prompts as svc

router = APIRouter(prefix="/projects/{project_id}/ux-prompts", tags=["ux-prompts"])

_MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


@router.get("/sources", response_model=UxPromptSources)
def get_sources(project_id: str, db: Session = Depends(get_db)):
    """The latest approved requirements version's epics/stories, the suggested
    mode, and the project's saved style brief. `document` is null until a
    version has been approved."""
    project = _get_project_or_404(db, project_id)
    return svc.list_sources(db, project)


@router.put("/style-brief", response_model=StyleBriefIO)
def save_style_brief(project_id: str, body: StyleBriefIO, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    return svc.save_style_brief(db, project, body)


@router.get("", response_model=list[UxPromptOut])
def list_prompts(project_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    return [svc.to_out(db, p) for p in svc.list_ux_prompts(db, project_id)]


@router.post("", response_model=UxPromptOut, status_code=201)
async def create_prompt(
    project_id: str,
    document_id: str = Form(...),
    epic_id: str = Form(...),
    story_ids: str = Form(..., description="JSON array of story item ids"),
    mode: UxPromptMode = Form(...),
    style_brief: Optional[str] = Form(None, description="JSON StyleBrief; saved as the project's brief"),
    screenshot: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    llm_client=Depends(get_openai_client),
):
    project = _get_project_or_404(db, project_id)

    try:
        ids = json.loads(story_ids)
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=422, detail="story_ids must be a JSON array of strings")

    try:
        brief = StyleBriefIO.model_validate_json(style_brief) if style_brief else StyleBriefIO()
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Invalid style_brief: {e.errors()[0]['msg']}")

    screenshot_bytes = None
    if screenshot is not None and screenshot.filename:
        suffix = "." + screenshot.filename.rsplit(".", 1)[-1].lower() if "." in screenshot.filename else ""
        if suffix not in _IMAGE_SUFFIXES:
            raise HTTPException(status_code=400, detail="Screenshot must be a .png, .jpg or .webp image")
        screenshot_bytes = await screenshot.read()
        if len(screenshot_bytes) > _MAX_SCREENSHOT_BYTES:
            raise HTTPException(status_code=413, detail="Screenshot is larger than 10 MB")

    try:
        prompt = svc.create_ux_prompt(
            db, project, document_id, epic_id, ids, mode, brief, llm_client, screenshot_bytes
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return svc.to_out(db, prompt)


@router.post("/{prompt_id}/regenerate", response_model=UxPromptOut)
def regenerate_prompt(
    project_id: str, prompt_id: str, db: Session = Depends(get_db), llm_client=Depends(get_openai_client)
):
    project = _get_project_or_404(db, project_id)
    try:
        prompt = svc.regenerate_ux_prompt(db, project, prompt_id, llm_client)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return svc.to_out(db, prompt)


@router.patch("/{prompt_id}", response_model=UxPromptOut)
def update_prompt(project_id: str, prompt_id: str, body: UxPromptEditUpdate, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    try:
        prompt = svc.update_edited_text(db, project_id, prompt_id, body.edited_text)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return svc.to_out(db, prompt)


@router.delete("/{prompt_id}", status_code=204)
def delete_prompt(project_id: str, prompt_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    try:
        svc.delete_ux_prompt(db, project_id, prompt_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
