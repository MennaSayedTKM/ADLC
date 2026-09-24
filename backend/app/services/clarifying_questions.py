"""
clarifying_questions.py
Phase 2 of the Requirements Intake Quality feature: reads everything staged
for a project (see intake_resources.py) and generates plain-language
questions a PM can relay to a non-technical stakeholder to fill real gaps
before extraction runs. Advisory only — generating, answering, or skipping
questions never blocks running extraction (Phase 4).
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ai.text.requirements_extractor import generate_clarifying_questions
from config import EXTRACTION_MODEL, GPT4O_INPUT_COST_PER_MILLION, GPT4O_OUTPUT_COST_PER_MILLION

from ..db.models import AiCall, ClarifyingQuestion, IntakeResource

_RESOURCE_KIND_LABEL = {
    "primary_requirements": "PRIMARY REQUIREMENTS",
    "meeting_notes": "MEETING NOTES",
    "policy_reference": "CLIENT POLICY REFERENCE",
    "other": "OTHER RESOURCE",
}


def _estimate_cost(usage) -> float:
    input_cost = (usage.prompt_tokens / 1_000_000) * GPT4O_INPUT_COST_PER_MILLION
    output_cost = (usage.completion_tokens / 1_000_000) * GPT4O_OUTPUT_COST_PER_MILLION
    return round(input_cost + output_cost, 6)


def build_combined_resource_text(resources: list[IntakeResource]) -> str:
    blocks = []
    for r in resources:
        if not r.extracted_text:
            continue
        label = _RESOURCE_KIND_LABEL.get(r.resource_kind, "OTHER RESOURCE")
        blocks.append(f"=== {label}: {r.original_filename} ===\n{r.extracted_text}")
    return "\n\n".join(blocks)


def generate_clarifying_questions_for_project(
    session: Session, project_id: str, llm_client, model: str = EXTRACTION_MODEL
) -> list[ClarifyingQuestion]:
    resources = (
        session.query(IntakeResource)
        .filter(IntakeResource.project_id == project_id, IntakeResource.extracted_text.isnot(None))
        .order_by(IntakeResource.uploaded_at)
        .all()
    )
    combined_text = build_combined_resource_text(resources)
    if not combined_text:
        raise ValueError("Stage at least one resource with successfully extracted text before generating questions.")

    questions_data, usage = generate_clarifying_questions(combined_text, llm_client, model)

    session.add(
        AiCall(
            project_id=project_id,
            call_type="clarifying_questions",
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            estimated_cost_usd=_estimate_cost(usage),
        )
    )

    questions = [
        ClarifyingQuestion(
            project_id=project_id,
            question_text=q["question"],
            topic_area=q["topic_area"],
            why_it_matters=q["why_it_matters"],
        )
        for q in questions_data
    ]
    session.add_all(questions)
    session.flush()
    return questions


def list_clarifying_questions(session: Session, project_id: str) -> list[ClarifyingQuestion]:
    return (
        session.query(ClarifyingQuestion)
        .filter(ClarifyingQuestion.project_id == project_id)
        .order_by(ClarifyingQuestion.created_at)
        .all()
    )


def _get_question_or_raise(session: Session, project_id: str, question_id: str) -> ClarifyingQuestion:
    question = (
        session.query(ClarifyingQuestion)
        .filter(ClarifyingQuestion.id == question_id, ClarifyingQuestion.project_id == project_id)
        .first()
    )
    if question is None:
        raise ValueError(f"Clarifying question {question_id} not found for project {project_id}")
    return question


def set_question_status(
    session: Session, project_id: str, question_id: str, status: str, answer_text: str | None = None
) -> ClarifyingQuestion:
    if status not in ("answered", "skipped", "pending"):
        raise ValueError(f"Invalid status: {status!r} — expected 'answered', 'skipped', or 'pending'")
    question = _get_question_or_raise(session, project_id, question_id)
    question.status = status
    question.answer_text = answer_text if status == "answered" else None
    question.answered_at = datetime.now(timezone.utc) if status in ("answered", "skipped") else None
    session.flush()
    return question
