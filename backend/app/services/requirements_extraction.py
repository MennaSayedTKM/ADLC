"""
requirements_extraction.py
Bridges ai/text/requirements_extractor.py to the SQLite schema: extracts text
from a requirement/change_request document, calls the LLM (gpt-4o for now —
see ai/text/requirements_extractor.py) for structured extraction, and
persists epics/stories/gaps.

Two entry points:
- run_extraction(): a fresh document (e.g. a new-project SOW) — persists
  directly onto `document`, every epic is new.
- run_change_request_extraction(): a CR filed against a project that already
  has an approved requirements baseline. Forks a new requirements version off
  that baseline (the same fork_new_version() mechanism edits-after-approval
  already use — see requirements_review.py) and merges the CR's new/extended
  items into it, rather than leaving the CR as a disconnected document.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.text.document_text import extract_text  # noqa: E402
from ai.text.requirements_extractor import (  # noqa: E402
    ExistingEpic,
    ensure_standing_policy_coverage,
    extract_change_request,
    extract_requirements,
    generate_item_draft,
    generate_suggestions,
)
from config import GPT4O_INPUT_COST_PER_MILLION, GPT4O_OUTPUT_COST_PER_MILLION  # noqa: E402

from ..db.models import AiCall, ClarifyingQuestion, Document, Gap, IntakeResource, Project, RequirementItem, StandingPolicy
from . import requirements_review as review
from .clarifying_questions import build_combined_resource_text


def _estimate_cost(usage) -> float:
    input_cost = (usage.prompt_tokens / 1_000_000) * GPT4O_INPUT_COST_PER_MILLION
    output_cost = (usage.completion_tokens / 1_000_000) * GPT4O_OUTPUT_COST_PER_MILLION
    return round(input_cost + output_cost, 6)


def _max_external_id_num(session: Session, document_id: str, item_type: str, prefix: str) -> int:
    rows = (
        session.query(RequirementItem.external_id)
        .filter(RequirementItem.document_id == document_id, RequirementItem.type == item_type)
        .all()
    )
    max_num = 0
    for (ext_id,) in rows:
        suffix = ext_id[len(prefix):] if ext_id.startswith(prefix) else ""
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    return max_num


def _renumber_new_items(session: Session, document_id: str, data: dict) -> None:
    """
    Reassigns every new epic/story in `data` a fresh, sequential external_id
    relative to what's already persisted for this document — never the id
    the LLM itself proposed. Confirmed directly: an LLM generating an
    incremental addition (a CR, a suggestions batch) has no visibility into
    what the target document already has, so it routinely proposes an id
    like "S23" for a document that only has S1-S8, or "E1" for what should
    be a brand new epic on a document that already has E1-E8 — each
    individually valid-looking, wrong once merged. The old fallback only
    renumbered on an exact string collision, which fixes duplicates but not
    a merely out-of-sequence id, which is what actually produced the
    reported "new item shows up as S23 / E10" and "sorts above the existing
    ones" symptoms (string-sorted "E10" sorts before "E2").

    Counts every existing row for this document+type toward the starting
    number regardless of suggestion_status — a pending or dismissed
    suggestion still occupies a real, DB-enforced-unique external_id slot,
    so it must still count even though it's hidden from the PM's main view.

    Mutates data["epics"]/data["user_stories"] in place, including updating
    every story's epic_id reference for any epic that got renumbered here;
    a story attaching to a pre-existing epic (not present in this batch) is
    left alone; the persist step below resolves that the same way as before.
    """
    epic_id_map: dict[str, str] = {}
    next_epic_n = _max_external_id_num(session, document_id, "epic", "E") + 1
    for epic in data["epics"]:
        new_id = f"E{next_epic_n}"
        next_epic_n += 1
        epic_id_map[epic["id"]] = new_id
        epic["id"] = new_id

    next_story_n = _max_external_id_num(session, document_id, "story", "S") + 1
    for story in data["user_stories"]:
        if story["epic_id"] in epic_id_map:
            story["epic_id"] = epic_id_map[story["epic_id"]]
        story["id"] = f"S{next_story_n}"
        next_story_n += 1


def _persist_epics_and_stories(session: Session, document: Document, data: dict) -> tuple[int, int]:
    _renumber_new_items(session, document.id, data)

    epic_id_map: dict[str, str] = {}  # extraction's own "E1" -> RequirementItem.id
    for epic in data["epics"]:
        row = RequirementItem(
            document_id=document.id,
            type="epic",
            external_id=epic["id"],
            text=epic["title"],
            assumptions=epic.get("assumptions") or None,
            dependencies=epic.get("dependencies") or None,
            source_reference=epic.get("source_reference") or None,
        )
        session.add(row)
        session.flush()
        epic_id_map[epic["id"]] = row.id

    for story in data["user_stories"]:
        parent_item_id = epic_id_map.get(story["epic_id"])
        if parent_item_id is None:
            # epic_id refers to a pre-existing epic already on this document
            # (change-request mode reusing a baseline epic).
            parent = (
                session.query(RequirementItem)
                .filter(
                    RequirementItem.document_id == document.id,
                    RequirementItem.external_id == story["epic_id"],
                    RequirementItem.type == "epic",
                )
                .first()
            )
            if parent is None:
                raise ValueError(
                    f"Story {story['id']!r} references epic_id {story['epic_id']!r} that isn't "
                    f"a new epic in this extraction or an existing epic on document {document.id}"
                )
            parent_item_id = parent.id

        session.add(
            RequirementItem(
                document_id=document.id,
                type="story",
                external_id=story["id"],
                parent_id=parent_item_id,
                text=story["title"],
                description=story.get("description"),
                scenarios=story.get("scenarios") or None,
                acceptance_criteria=story.get("acceptance_criteria") or None,
                error_handling=story.get("error_handling") or None,
            )
        )

    return len(data["epics"]), len(data["user_stories"])


def _persist_gaps(session: Session, document: Document, data: dict) -> int:
    for gap in data["gaps"]:
        session.add(
            Gap(
                document_id=document.id,
                description=gap["description"],
                location=gap.get("location"),
                severity=gap["severity"],
            )
        )
    return len(data["gaps"])


def _persist_suggestions(session: Session, document: Document, data: dict) -> int:
    """
    Same shape as _persist_epics_and_stories, but every row lands with
    origin="ai_suggestion" and suggestion_status="pending" — hidden from
    the normal epics/stories views until a PM accepts or dismisses it (see
    routers/requirements.py's _detail_for and requirements_review.py's
    accept_suggestion/dismiss_suggestion). gaps is unused here; the
    suggestions extraction never populates it.
    """
    _renumber_new_items(session, document.id, data)

    epic_id_map: dict[str, str] = {}
    for epic in data["epics"]:
        row = RequirementItem(
            document_id=document.id,
            type="epic",
            external_id=epic["id"],
            text=epic["title"],
            assumptions=epic.get("assumptions") or None,
            dependencies=epic.get("dependencies") or None,
            origin="ai_suggestion",
            suggestion_status="pending",
        )
        session.add(row)
        session.flush()
        epic_id_map[epic["id"]] = row.id

    added = 0
    for story in data["user_stories"]:
        parent_item_id = epic_id_map.get(story["epic_id"])
        if parent_item_id is None:
            parent = (
                session.query(RequirementItem)
                .filter(
                    RequirementItem.document_id == document.id,
                    RequirementItem.external_id == story["epic_id"],
                    RequirementItem.type == "epic",
                )
                .first()
            )
            if parent is None:
                # A suggestion referencing an epic that no longer resolves
                # (shouldn't happen — generate_suggestions() validates this
                # — but suggestions are advisory-only, so skip rather than
                # blow up the whole batch over one bad entry).
                continue
            parent_item_id = parent.id

        session.add(
            RequirementItem(
                document_id=document.id,
                type="story",
                external_id=story["id"],
                parent_id=parent_item_id,
                text=story["title"],
                description=story.get("description"),
                scenarios=story.get("scenarios") or None,
                acceptance_criteria=story.get("acceptance_criteria") or None,
                error_handling=story.get("error_handling") or None,
                origin="ai_suggestion",
                suggestion_status="pending",
            )
        )
        added += 1

    return added


def log_ai_call(session: Session, document: Document, model: str, usage, call_type: str = "extraction") -> None:
    session.add(
        AiCall(
            document_id=document.id,
            call_type=call_type,
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            estimated_cost_usd=_estimate_cost(usage),
        )
    )


def _build_final_data(session: Session, document_id: str) -> dict:
    """
    Reconstructs the {"epics": [...], "user_stories": [...]} shape
    generate_suggestions() expects, from what's actually persisted on a
    document — used for the change-request path, where the freshly-merged
    `data` alone would miss the untouched baseline epics a suggestion might
    reasonably want to attach to. Excludes pending/dismissed suggestions —
    those aren't real, confirmed content yet, so a new suggestions call
    shouldn't treat them as an already-covered story when deciding what's
    genuinely missing.
    """
    items = (
        session.query(RequirementItem)
        .filter(RequirementItem.document_id == document_id, RequirementItem.suggestion_status.is_(None))
        .all()
    )
    epics = [i for i in items if i.type == "epic"]
    stories = [i for i in items if i.type == "story"]
    return {
        "epics": [{"id": e.external_id, "title": e.text} for e in epics],
        "user_stories": [
            {
                "id": s.external_id,
                "epic_id": next((e.external_id for e in epics if e.id == s.parent_id), ""),
                "title": s.text,
                "description": s.description or "",
                "scenarios": s.scenarios or [],
                "acceptance_criteria": s.acceptance_criteria or [],
                "error_handling": s.error_handling or [],
            }
            for s in stories
        ],
    }


def _run_suggestions(session: Session, document: Document, text: str, final_data: dict, llm_client, model: str) -> None:
    """
    Automatic, best-effort 5th step run right after a fresh extraction (or
    CR merge) finishes — advisory bonus content, so a failure here must
    never take down the primary deliverable (the real epics/stories/gaps
    the PM actually needs). See generate_suggestions()'s own docstring for
    why validation is lenient. Errors are swallowed rather than propagated
    (a suggestions failure must never turn into a failed upload), but ARE
    logged — a real run silently produced zero suggestions with literally
    no trace anywhere (no error, no AiCall row, nothing to distinguish
    "never ran" from "ran and failed") until reproduced by hand outside the
    app; logging is the fix for that, not a retry, since this content is
    advisory and the PM was never depending on it existing.
    """
    # final_data (see _build_final_data) deliberately excludes epics from a
    # still-pending earlier suggestion — an unconfirmed suggestion shouldn't
    # count as "already covered" when deciding what's genuinely missing. But
    # that pending epic's external_id is still a real, persisted row for
    # this exact document, so it must still be visible to id-collision
    # detection — otherwise a new batch can reuse it and the collision is
    # invisible to both _renumber_colliding_ids and validate_extraction
    # (both keyed off the same set), surfacing only as a raw database
    # UNIQUE-constraint crash. Confirmed directly: this is exactly what
    # happened against a real project with a pending "E9" suggestion.
    reserved_epic_ids = {
        e.external_id
        for e in session.query(RequirementItem)
        .filter(RequirementItem.document_id == document.id, RequirementItem.type == "epic")
        .all()
    }
    try:
        suggestions_data, suggestions_usage = generate_suggestions(
            text, final_data, llm_client, model=model, reserved_epic_ids=reserved_epic_ids
        )
    except (ValueError, KeyError):
        logger.warning(
            "Suggestions generation failed for document %s — skipping (advisory only, upload unaffected)",
            document.id,
            exc_info=True,
        )
        return

    # Persisting runs inside its own SAVEPOINT, not the request's outer
    # transaction — a persistence-time failure here (e.g. an id collision
    # that slipped past the checks above) must roll back only the
    # suggestions themselves, not the CR merge / main extraction already
    # flushed earlier in this same request. Without this, a suggestions
    # crash rolls back the entire outer transaction on the way out (see
    # db/session.py's get_session: any uncaught exception rolls back
    # everything), which silently contradicts this function's own "must
    # never take down the primary deliverable" promise — confirmed
    # directly: exactly this happened against a real project.
    try:
        with session.begin_nested():
            _persist_suggestions(session, document, suggestions_data)
            log_ai_call(session, document, model, suggestions_usage, call_type="suggestions")
    except SQLAlchemyError:
        logger.warning(
            "Persisting suggestions failed for document %s — skipping (advisory only, upload unaffected)",
            document.id,
            exc_info=True,
        )


def build_staged_extraction_text(session: Session, project_id: str) -> str:
    """
    Combines every staged intake resource, every answered clarifying
    question, and every active standing policy into one labeled text blob —
    see _shared_instructions()'s MULTI-SOURCE MATERIAL section for how the
    model is told to treat each block. Reused by both run_staged_extraction
    (the initial call) and run_suggestions_background (re-deriving the same
    source text for a staged-extraction document, which has no single
    source_file_path to re-read from disk).
    """
    resources = (
        session.query(IntakeResource)
        .filter(IntakeResource.project_id == project_id, IntakeResource.extracted_text.isnot(None))
        .order_by(IntakeResource.uploaded_at)
        .all()
    )
    blocks = [build_combined_resource_text(resources)]

    answered = (
        session.query(ClarifyingQuestion)
        .filter(ClarifyingQuestion.project_id == project_id, ClarifyingQuestion.status == "answered")
        .order_by(ClarifyingQuestion.created_at)
        .all()
    )
    if answered:
        qa_lines = "\n".join(f"Q: {q.question_text}\nA: {q.answer_text}" for q in answered)
        blocks.append(f"=== STAKEHOLDER CLARIFYING Q&A ===\n{qa_lines}")

    policies = (
        session.query(StandingPolicy)
        .filter(StandingPolicy.is_active.is_(True))
        .order_by(StandingPolicy.created_at)
        .all()
    )
    if policies:
        policy_lines = "\n".join(f"- {p.title}: {p.policy_text}" for p in policies)
        blocks.append(
            "=== TKMIND STANDARD POLICIES (fallback only — apply ONLY where nothing above "
            "already addresses the same topic) ===\n" + policy_lines
        )

    return "\n\n".join(blocks)


def run_staged_extraction(
    session: Session, project: Project, llm_client, model: str
) -> tuple[Document, int, int, int]:
    """
    Initial extraction (creating v1 of a project's requirements) from
    everything staged for the project — see intake_resources.py,
    clarifying_questions.py, standing_policies.py. Explicitly out of scope:
    updating an already-extracted project continues to go through the
    existing Change Request flow, not this function — see
    build_staged_extraction_text and this feature's plan for why that's a
    meaningfully different problem.
    """
    has_primary = (
        session.query(IntakeResource)
        .filter(
            IntakeResource.project_id == project.id,
            IntakeResource.resource_kind == "primary_requirements",
            IntakeResource.extracted_text.isnot(None),
        )
        .first()
        is not None
    )
    if not has_primary:
        raise ValueError(
            "Stage at least one primary requirements resource with successfully extracted "
            "text before running extraction."
        )

    text = build_staged_extraction_text(session, project.id)

    resource_count = session.query(IntakeResource).filter(IntakeResource.project_id == project.id).count()
    document = Document(
        project_id=project.id,
        doc_type="requirement",
        source_filename=f"Staged resources ({resource_count} file{'s' if resource_count != 1 else ''})",
    )
    session.add(document)
    session.flush()

    data, usage = extract_requirements(text, llm_client, model=model)

    # A dedicated audit+repair pass, not one more instruction inside
    # extract_requirements() itself — see ensure_standing_policy_coverage()'s
    # docstring in ai/text/requirements_extractor.py for why a single call
    # given both jobs at once proved unreliable, confirmed directly against
    # two live runs. Logged as its own AiCall (call_type="policy_coverage")
    # rather than merged into the main extraction's usage, matching how
    # suggestions gets its own call_type rather than being folded in.
    active_policies = [
        (p.title, p.policy_text)
        for p in session.query(StandingPolicy).filter(StandingPolicy.is_active.is_(True)).all()
    ]
    data, policy_usages = ensure_standing_policy_coverage(data, active_policies, llm_client, model)

    epics_added, stories_added = _persist_epics_and_stories(session, document, data)
    gaps_added = _persist_gaps(session, document, data)
    log_ai_call(session, document, model, usage)
    for policy_usage in policy_usages:
        log_ai_call(session, document, model, policy_usage, call_type="policy_coverage")
    session.flush()

    return document, epics_added, stories_added, gaps_added


def run_extraction(
    session: Session, document: Document, llm_client, model: str
) -> tuple[Document, int, int, int]:
    """
    Fresh requirement document (e.g. a new-project SOW) — every epic is new.
    Suggestions are NOT generated here — see run_suggestions_background()
    below, scheduled by the router as a FastAPI BackgroundTask after the
    response is sent. Suggestions are advisory bonus content the PM never
    asked for; blocking the upload response on one more full LLM call (plus
    its own retry-on-malformed-JSON attempts) for content that isn't the
    primary deliverable was confirmed directly to be a meaningful chunk of
    perceived upload latency.
    """
    text = extract_text(Path(document.source_file_path))
    data, usage = extract_requirements(text, llm_client, model=model)

    epics_added, stories_added = _persist_epics_and_stories(session, document, data)
    gaps_added = _persist_gaps(session, document, data)
    log_ai_call(session, document, model, usage)
    session.flush()

    return document, epics_added, stories_added, gaps_added


def run_suggestions_background(document_id: str, llm_client, model: str) -> None:
    """
    Entry point for the BackgroundTask the router schedules after an upload
    response has already been sent — must open its OWN session rather than
    reusing the request's, which get_session() has already committed and
    closed by the time a background task runs (FastAPI/Starlette run a
    yield-dependency's post-yield cleanup before background tasks, not
    after). Re-reads the document and its persisted content fresh rather
    than threading `data`/`text` across that session boundary — simpler,
    and correct regardless of what else changed on the document in the
    meantime. Never raises past this point: there is no request left to
    report a failure to, so _run_suggestions' own logging is the only
    record of a failure here, exactly as it already is for a persistence-
    time failure.
    """
    from ..db.session import get_session

    with get_session() as session:
        document = session.query(Document).filter(Document.id == document_id).first()
        if document is None:
            return  # deleted, or forked into a newer version, before this ran
        if document.source_file_path:
            text = extract_text(Path(document.source_file_path))
        else:
            # A staged-extraction document (see run_staged_extraction) has no
            # single source file to re-read — rebuild the same combined text
            # it was originally extracted from instead.
            text = build_staged_extraction_text(session, document.project_id)
        final_data = _build_final_data(session, document.id)
        _run_suggestions(session, document, text, final_data, llm_client, model)


def run_change_request_extraction(
    session: Session,
    cr_document: Document,
    approved_document: Document,
    llm_client,
    model: str,
) -> tuple[Document, int, int, int]:
    """
    Extracts `cr_document` against `approved_document`'s approved epics, forks
    a new requirements version off `approved_document`, and merges the CR's
    new/extended items into that fork.
    """
    text = extract_text(Path(cr_document.source_file_path))

    existing_epics = [
        ExistingEpic(external_id=e.external_id, title=e.text)
        for e in session.query(RequirementItem)
        .filter(RequirementItem.document_id == approved_document.id, RequirementItem.type == "epic")
        .all()
    ]

    data, usage = extract_change_request(text, existing_epics, llm_client, model=model)

    new_version = review.fork_new_version(session, approved_document)
    new_version.type_metadata = {
        **(new_version.type_metadata or {}),
        "source_change_request_id": cr_document.id,
    }

    epics_added, stories_added = _persist_epics_and_stories(session, new_version, data)
    gaps_added = _persist_gaps(session, new_version, data)
    log_ai_call(session, cr_document, model, usage)
    session.flush()

    # Suggestions run as a background task after the response is sent — see
    # run_suggestions_background() / run_extraction()'s matching docstring.

    cr_document.type_metadata = {
        **(cr_document.type_metadata or {}),
        "produced_requirements_document_id": new_version.id,
    }

    return new_version, epics_added, stories_added, gaps_added


def _condensed_project_context(session: Session, document_id: str) -> str:
    """
    A short "E1 — Title / S1. Title — description" listing of what's
    already on this document (excluding pending/dismissed suggestions —
    only the real, visible tree), so AI-assisted single-item generation
    stays consistent with the project's established roles/voice instead of
    inventing a new actor for every add.
    """
    items = (
        session.query(RequirementItem)
        .filter(
            RequirementItem.document_id == document_id,
            RequirementItem.suggestion_status.is_(None),
        )
        .order_by(RequirementItem.created_at)
        .all()
    )
    epics = [i for i in items if i.type == "epic"]
    lines: list[str] = []
    for epic in epics:
        lines.append(f"{epic.external_id} — {epic.text}")
        for story in items:
            if story.type == "story" and story.parent_id == epic.id:
                suffix = f" — {story.description}" if story.description else ""
                lines.append(f"  {story.external_id}. {story.text}{suffix}")
    return "\n".join(lines)


_STORY_LEVEL_KINDS = ("acceptance_criterion", "scenario", "error_handling")


def generate_item_draft_for_document(
    session: Session,
    document: Document,
    kind: str,
    subject: str,
    client,
    model: str,
    parent_id: Optional[str] = None,
    previous_draft: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], Any]:
    """
    PM-initiated AI-assisted item generation — builds the project context
    (and, for a story or a story-level piece, the specific parent's
    context) from what's already on this document, then calls
    ai/text/requirements_extractor.generate_item_draft(). Returns the raw
    draft for the caller to show the PM to review; nothing is persisted
    here — the router's confirm step goes through the existing
    requirements_review.create_item()/edit_item() instead, same path a
    plain manual add uses, just with origin="pm_ai_assisted".

    Pass `previous_draft` (this function's own prior return value for the
    same subject) when the PM clicked Regenerate — see
    generate_item_draft()'s docstring for why that changes the call.
    """
    if kind not in ("epic", "story", *_STORY_LEVEL_KINDS):
        raise ValueError(f"Invalid kind: {kind!r}")

    project_context = _condensed_project_context(session, document.id)

    parent_context = ""
    if kind == "story":
        if not parent_id:
            raise ValueError("parent_id (the epic) is required to draft a story")
        epic = (
            session.query(RequirementItem)
            .filter(
                RequirementItem.id == parent_id,
                RequirementItem.document_id == document.id,
                RequirementItem.type == "epic",
            )
            .first()
        )
        if epic is None:
            raise ValueError(f"Epic {parent_id} not found on document {document.id}")
        parent_context = f"This story belongs under epic {epic.external_id} — {epic.text}."
    elif kind in _STORY_LEVEL_KINDS:
        if not parent_id:
            raise ValueError(f"parent_id (the story) is required to draft {kind.replace('_', ' ')}")
        story = (
            session.query(RequirementItem)
            .filter(
                RequirementItem.id == parent_id,
                RequirementItem.document_id == document.id,
                RequirementItem.type == "story",
            )
            .first()
        )
        if story is None:
            raise ValueError(f"Story {parent_id} not found on document {document.id}")
        existing_ac = "\n".join(f"- {ac['text']}" for ac in (story.acceptance_criteria or []))
        existing_scenarios = "\n".join(f"- {sc['title']}" for sc in (story.scenarios or []))
        existing_eh = "\n".join(f"- {eh['condition']} -> {eh['message']}" for eh in (story.error_handling or []))
        description_suffix = f": {story.description}" if story.description else ""
        parent_context = (
            f"This belongs to story {story.external_id} — {story.text}{description_suffix}.\n"
            f"Existing acceptance criteria:\n{existing_ac or '(none yet)'}\n"
            f"Existing scenarios:\n{existing_scenarios or '(none yet)'}\n"
            f"Existing error handling:\n{existing_eh or '(none yet)'}"
        )

    draft, usage = generate_item_draft(
        kind,
        subject,
        client,
        model=model,
        project_context=project_context,
        parent_context=parent_context,
        previous_draft=previous_draft,
    )
    log_ai_call(session, document, model, usage, call_type="item_draft")
    return draft, usage
