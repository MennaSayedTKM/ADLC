"""Company-wide settings (see services/app_settings.py)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..services import app_settings as svc

router = APIRouter(prefix="/settings", tags=["settings"])


class JiraDefaultOut(BaseModel):
    default_project_key: Optional[str] = None


class JiraDefaultIn(BaseModel):
    default_project_key: str = ""  # empty clears it


@router.get("/jira", response_model=JiraDefaultOut)
def get_jira_default(db: Session = Depends(get_db)):
    return {"default_project_key": svc.get_jira_default_project_key(db)}


@router.put("/jira", response_model=JiraDefaultOut)
def set_jira_default(body: JiraDefaultIn, db: Session = Depends(get_db)):
    try:
        return {"default_project_key": svc.set_jira_default_project_key(db, body.default_project_key)}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
