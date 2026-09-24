from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db.models import Project
from ..db.session import get_db
from ..schemas.projects import ProjectCreate, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.query(Project).filter(Project.name == body.name).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Project {body.name!r} already exists")
    project = Project(name=body.name)
    db.add(project)
    db.flush()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()
