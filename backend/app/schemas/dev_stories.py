from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .requirements import DocumentOut

TaskArea = Literal["frontend", "backend", "data", "integration", "infrastructure", "testing"]


class TechProfileOut(BaseModel):
    areas: dict[str, str]  # area key -> what the company specified ("" = not specified)
    document_name: Optional[str] = None
    document_chars: int = 0


class TechProfileIn(BaseModel):
    areas: dict[str, str]


class TechDocumentRead(TechProfileOut):
    """An uploaded tech document: its text is stored; the areas it specifies are
    merged into the empty fields for the person to review and save."""

    read_from_document: dict[str, str]


class DevTaskOut(BaseModel):
    id: str
    position: int
    title: str
    summary: str
    area: str
    coding_prompt: Optional[str] = None
    edited_prompt: Optional[str] = None
    tech_decision_needed: bool = False
    decision_areas: list[str] = []
    prompt_generated_at: Optional[datetime] = None
    screens: list[dict[str, Any]] = []
    jira_key: Optional[str] = None
    jira_url: Optional[str] = None


class DevStoryOut(BaseModel):
    id: str
    epic_external_id: str
    source_story_external_id: Optional[str] = None
    position: int
    title: str
    description: str
    acceptance_criteria: list[str] = []
    story_points: Optional[int] = None
    labels: list[str] = []
    jira_key: Optional[str] = None
    jira_url: Optional[str] = None
    is_stale: bool = False  # planned from an older approved version
    tasks: list[DevTaskOut] = []


class SourceStoryRef(BaseModel):
    id: str
    external_id: str
    title: str


class DevEpicOut(BaseModel):
    external_id: str
    title: str
    stories: list[SourceStoryRef] = []
    dev_stories: list[DevStoryOut] = []


class DevOverviewOut(BaseModel):
    document: Optional[DocumentOut] = None  # latest approved requirements version; null until one exists
    tech_profile: TechProfileOut
    unspecified_areas: list[str] = []
    epics: list[DevEpicOut] = []  # in dependency order


class DevStoryUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    acceptance_criteria: Optional[list[str]] = None
    story_points: Optional[int] = Field(default=None, ge=0, le=100)
    labels: Optional[list[str]] = None


class DevTaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    summary: Optional[str] = None
    area: Optional[TaskArea] = None
    edited_prompt: Optional[str] = None  # null resets to the generated prompt
