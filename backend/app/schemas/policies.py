from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class StandingPolicyOut(BaseModel):
    id: str
    title: str
    policy_text: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StandingPolicyCreate(BaseModel):
    title: str
    policy_text: str


class StandingPolicyUpdate(BaseModel):
    title: Optional[str] = None
    policy_text: Optional[str] = None
    is_active: Optional[bool] = None


class PolicyDraftRequest(BaseModel):
    subject: str
    # This call's own prior response, when the PM clicked Regenerate rather
    # than confirming — see generate_policy_draft()'s docstring for why.
    previous_draft: Optional[dict[str, str]] = None


class PolicyDraftOut(BaseModel):
    title: str
    policy_text: str
