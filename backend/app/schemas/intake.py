from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

IntakeResourceKind = Literal["primary_requirements", "meeting_notes", "policy_reference", "other"]
ClarifyingQuestionStatus = Literal["pending", "answered", "skipped"]


class IntakeResourceOut(BaseModel):
    id: str
    project_id: str
    resource_kind: str
    original_filename: str
    file_type: str
    extracted_text: Optional[str] = None
    processing_error: Optional[str] = None
    notes: Optional[str] = None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class ClarifyingQuestionOut(BaseModel):
    id: str
    project_id: str
    question_text: str
    topic_area: Optional[str] = None
    why_it_matters: Optional[str] = None
    status: str
    answer_text: Optional[str] = None
    created_at: datetime
    answered_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ClarifyingQuestionStatusUpdate(BaseModel):
    status: ClarifyingQuestionStatus
    answer_text: Optional[str] = None
