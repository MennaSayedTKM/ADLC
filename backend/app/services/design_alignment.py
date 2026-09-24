"""
design_alignment.py
Bridges ai/vision/alignment_checker.py to the SQLite schema: for a design
document, runs one GPT-4o alignment check per screen (= per ingested page)
against the approved requirement stories, and persists one alignment_reports
row per screen plus its alignment_findings rows.
"""

import sys
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.ingest.ingest import tiles_for_document  # noqa: E402
from ai.vision.alignment_checker import ApprovedStory, check_alignment  # noqa: E402
from config import GPT4O_INPUT_COST_PER_MILLION, GPT4O_OUTPUT_COST_PER_MILLION  # noqa: E402

from ..db.models import AiCall, AlignmentFinding, AlignmentReport, Document, RequirementItem


def _estimate_cost(usage) -> float:
    input_cost = (usage.prompt_tokens / 1_000_000) * GPT4O_INPUT_COST_PER_MILLION
    output_cost = (usage.completion_tokens / 1_000_000) * GPT4O_OUTPUT_COST_PER_MILLION
    return round(input_cost + output_cost, 6)


def _ac_to_strings(acceptance_criteria: list | None) -> list[str]:
    """
    ApprovedStory (ai/vision/alignment_checker.py) predates the requirements
    rework and still expects plain-string acceptance criteria — the DB column
    now stores {"text", "out_of_scope"} objects (shared with the requirements
    module), so they're flattened to strings here rather than changing that
    module's typed dataclass.
    """
    if not acceptance_criteria:
        return []
    out = []
    for ac in acceptance_criteria:
        if isinstance(ac, dict):
            text = ac.get("text", "")
            out.append(f"{text} (out of scope)" if ac.get("out_of_scope") else text)
        else:
            out.append(ac)
    return out


def _story_rows(session: Session, requirements_document_id: str) -> list[RequirementItem]:
    return (
        session.query(RequirementItem)
        .filter(
            RequirementItem.document_id == requirements_document_id,
            RequirementItem.type == "story",
        )
        .all()
    )


def get_approved_stories(session: Session, requirements_document_id: str) -> list[ApprovedStory]:
    return [
        ApprovedStory(
            external_id=r.external_id, text=r.text, acceptance_criteria=_ac_to_strings(r.acceptance_criteria)
        )
        for r in _story_rows(session, requirements_document_id)
    ]


def _load_screens(document_id: str) -> list[tuple[int, Image.Image]]:
    tiles = tiles_for_document(document_id)
    if not tiles:
        raise ValueError(f"No tiles found for document {document_id} — was it ingested?")
    return [(t["page"], Image.open(t["tile_path"]).convert("RGB")) for t in tiles]


def run_alignment_check(
    session: Session,
    design_document: Document,
    requirements_document: Document,
    openai_client,
    model: str,
) -> list[AlignmentReport]:
    """
    Runs one GPT-4o alignment call per screen in `design_document`, persists
    an alignment_reports + alignment_findings rows per screen, and logs each
    call to ai_calls. Returns the created AlignmentReport rows.
    """
    story_rows = _story_rows(session, requirements_document.id)
    stories = [
        ApprovedStory(external_id=r.external_id, text=r.text, acceptance_criteria=_ac_to_strings(r.acceptance_criteria))
        for r in story_rows
    ]
    story_id_to_item_id = {r.external_id: r.id for r in story_rows}

    screens = _load_screens(design_document.id)
    reports = []

    for page_num, screen_image in screens:
        # Every other screen in this upload goes in as low-detail context so
        # the model doesn't flag a requirement as "missing" here when it's
        # actually satisfied on a different screen in the same flow.
        context_screens = [(p, img) for p, img in screens if p != page_num]
        data, usage = check_alignment(
            screen_image, stories, openai_client, model=model, context_screens=context_screens
        )

        report = AlignmentReport(
            design_document_id=design_document.id,
            requirements_document_id=requirements_document.id,
            page=page_num,
            status=data["status"],
        )
        session.add(report)
        session.flush()

        for finding in data["findings"]:
            session.add(
                AlignmentFinding(
                    alignment_report_id=report.id,
                    requirement_item_id=story_id_to_item_id.get(finding["requirement_id"]),
                    issue=finding["issue"],
                    recommendation=finding["recommendation"],
                    bounding_box=finding.get("bounding_box"),
                )
            )

        session.add(
            AiCall(
                document_id=design_document.id,
                call_type="alignment",
                model=model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                estimated_cost_usd=_estimate_cost(usage),
            )
        )

        reports.append(report)

    return reports


def set_finding_status(session: Session, design_document_id: str, finding_id: str, status: str) -> AlignmentFinding:
    if status not in ("open", "resolved", "dismissed"):
        raise ValueError(f"Invalid finding status: {status!r}")

    finding = (
        session.query(AlignmentFinding)
        .join(AlignmentReport, AlignmentFinding.alignment_report_id == AlignmentReport.id)
        .filter(
            AlignmentFinding.id == finding_id,
            AlignmentReport.design_document_id == design_document_id,
        )
        .first()
    )
    if finding is None:
        raise ValueError(f"Finding {finding_id} not found on design document {design_document_id}")
    finding.resolution_status = status
    return finding
