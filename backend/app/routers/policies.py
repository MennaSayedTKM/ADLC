"""
policies.py
Global (not per-project) CRUD for the platform's standing policies — Phase 3
of the Requirements Intake Quality feature. See
backend/app/services/standing_policies.py for the persistence this router
calls into.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..deps import get_openai_client
from ..schemas.policies import (
    PolicyDraftOut,
    PolicyDraftRequest,
    StandingPolicyCreate,
    StandingPolicyOut,
    StandingPolicyUpdate,
)
from ..services.standing_policies import (
    create_standing_policy,
    generate_policy_draft_for_pm,
    list_standing_policies,
    update_standing_policy,
)

# db.session (imported above) already put the repo root on sys.path, so this
# resolves the same way config.py does everywhere else in the app.
from config import EXTRACTION_MODEL  # noqa: E402

router = APIRouter(prefix="/policies", tags=["policies"])


@router.post("", response_model=StandingPolicyOut, status_code=201)
def create_policy(body: StandingPolicyCreate, db: Session = Depends(get_db)):
    policy = create_standing_policy(db, body.title, body.policy_text)
    db.refresh(policy)
    return policy


@router.post("/generate-draft", response_model=PolicyDraftOut)
def generate_policy_draft_endpoint(
    body: PolicyDraftRequest, db: Session = Depends(get_db), llm_client=Depends(get_openai_client)
):
    """
    Drafts a policy from a PM-supplied subject — advisory only, nothing is
    persisted here; the PM reviews/edits the draft and confirms via the
    normal POST /policies to actually save it.
    """
    try:
        draft = generate_policy_draft_for_pm(
            db, body.subject, llm_client, model=EXTRACTION_MODEL, previous_draft=body.previous_draft
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.flush()
    return draft


@router.get("", response_model=list[StandingPolicyOut])
def get_policies(db: Session = Depends(get_db)):
    return list_standing_policies(db)


@router.patch("/{policy_id}", response_model=StandingPolicyOut)
def edit_policy(policy_id: str, body: StandingPolicyUpdate, db: Session = Depends(get_db)):
    try:
        policy = update_standing_policy(
            db, policy_id, title=body.title, policy_text=body.policy_text, is_active=body.is_active
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    db.refresh(policy)
    return policy
