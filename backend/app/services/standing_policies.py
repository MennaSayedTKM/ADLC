"""
standing_policies.py
Phase 3 of the Requirements Intake Quality feature: baseline default
requirements — universal software-delivery good practice, not tied to any
one client — PM-managed and global (not per-project). Phase 4's
run_staged_extraction() folds every active policy in as a fallback-only
source — the client's own material always wins on the same topic.
"""

from typing import Optional

from sqlalchemy.orm import Session

from ai.text.requirements_extractor import generate_policy_draft
from config import EXTRACTION_MODEL, GPT4O_INPUT_COST_PER_MILLION, GPT4O_OUTPUT_COST_PER_MILLION

from ..db.models import AiCall, StandingPolicy


def _estimate_cost(usage) -> float:
    input_cost = (usage.prompt_tokens / 1_000_000) * GPT4O_INPUT_COST_PER_MILLION
    output_cost = (usage.completion_tokens / 1_000_000) * GPT4O_OUTPUT_COST_PER_MILLION
    return round(input_cost + output_cost, 6)


def generate_policy_draft_for_pm(
    session: Session,
    subject: str,
    llm_client,
    model: str = EXTRACTION_MODEL,
    previous_draft: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """
    Drafts a policy from a PM-supplied subject — nothing is persisted here,
    same "advisory draft, PM confirms before saving" shape as every other
    AI-assisted draft in this system (see generate_item_draft_for_document).
    Logged as call_type="item_draft" — the same generic bucket every other
    PM-initiated single-item AI draft already uses, not a new category.
    """
    draft, usage = generate_policy_draft(subject, llm_client, model=model, previous_draft=previous_draft)
    session.add(
        AiCall(
            call_type="item_draft",
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            estimated_cost_usd=_estimate_cost(usage),
        )
    )
    return draft


def create_standing_policy(session: Session, title: str, policy_text: str) -> StandingPolicy:
    policy = StandingPolicy(title=title, policy_text=policy_text)
    session.add(policy)
    session.flush()
    return policy


def list_standing_policies(session: Session, active_only: bool = False) -> list[StandingPolicy]:
    query = session.query(StandingPolicy)
    if active_only:
        query = query.filter(StandingPolicy.is_active.is_(True))
    return query.order_by(StandingPolicy.created_at).all()


def update_standing_policy(
    session: Session,
    policy_id: str,
    title: str | None = None,
    policy_text: str | None = None,
    is_active: bool | None = None,
) -> StandingPolicy:
    policy = session.query(StandingPolicy).filter(StandingPolicy.id == policy_id).first()
    if policy is None:
        raise ValueError(f"Standing policy {policy_id} not found")
    if title is not None:
        policy.title = title
    if policy_text is not None:
        policy.policy_text = policy_text
    if is_active is not None:
        policy.is_active = is_active
    session.flush()
    return policy
