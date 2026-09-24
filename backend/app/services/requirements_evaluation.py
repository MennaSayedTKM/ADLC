"""
requirements_evaluation.py
On-demand quality evaluation of a requirements document's CURRENT visible
tree — never automatic (see requirements_extraction.py's own docstring on
why an extra LLM call after every extraction was rejected: perceived upload
latency is an explicit standing complaint). Three independent GPT-4o review
agents (see ai/text/requirements_extractor.py::review_source_material /
review_output_stories / review_advisory_artifacts) run CONCURRENTLY via
ThreadPoolExecutor — safe here (unlike _spawn_suggestions_thread's
background-thread deadlock) because these three calls are pure, session-free
functions: no DB access happens inside any of them, so there's no
_write_lock contention risk. Deterministic signals + a documented formula
(_synthesize_scores) blend the agents' scores — no 4th LLM call, for the
same reliability reasoning this codebase already applies elsewhere (see
ensure_standing_policy_coverage).
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy.orm import Session

from ai.text.document_text import extract_text
from ai.text.requirements_extractor import (
    review_advisory_artifacts,
    review_output_stories,
    review_source_material,
)

from ..db.models import Document, EvaluationReport, Gap, RequirementItem
from .requirements_extraction import build_staged_extraction_text, log_ai_call

_POLICY_SOURCE_PREFIX = "TKMiND Standard Policy — "


def _build_story_review_payload(visible_items: list[RequirementItem]) -> tuple[list[dict], list[dict]]:
    epics = [i for i in visible_items if i.type == "epic"]
    stories = [i for i in visible_items if i.type == "story"]
    epics_payload = [{"id": e.external_id, "title": e.text} for e in epics]
    stories_payload = [
        {
            "id": s.external_id,
            "epic_id": next((e.external_id for e in epics if e.id == s.parent_id), ""),
            "title": s.text,
            "description": s.description or "",
            "acceptance_criteria": [ac["text"] for ac in (s.acceptance_criteria or [])],
            "scenarios": s.scenarios or [],
            "error_handling": s.error_handling or [],
        }
        for s in stories
    ]
    return epics_payload, stories_payload


def _build_artifact_review_payload(
    all_items: list[RequirementItem], visible_items: list[RequirementItem], gaps: list[Gap]
) -> tuple[list[dict], list[dict], list[dict]]:
    gaps_payload = [
        {"id": g.id, "description": g.description, "severity": g.severity, "status": g.status} for g in gaps
    ]
    suggestions_payload = [
        {"id": i.external_id, "title": i.text, "description": i.description or "", "status": i.suggestion_status}
        for i in all_items
        if i.origin == "ai_suggestion"
    ]
    policy_stories_payload = [
        {"id": i.external_id, "title": i.text, "description": i.description or "", "policy_title": i.source_reference}
        for i in visible_items
        if (i.source_reference or "").startswith(_POLICY_SOURCE_PREFIX)
    ]
    return gaps_payload, suggestions_payload, policy_stories_payload


def _compute_signals(all_items: list[RequirementItem], visible_items: list[RequirementItem], gaps: list[Gap]) -> dict:
    return {
        "total_epic_count": sum(1 for i in visible_items if i.type == "epic"),
        "total_story_count": sum(1 for i in visible_items if i.type == "story"),
        "gap_count": len(gaps),
        "high_severity_gap_count": sum(1 for g in gaps if g.severity == "high"),
        "open_gap_count": sum(1 for g in gaps if g.status == "open"),
        "open_high_severity_gap_count": sum(1 for g in gaps if g.severity == "high" and g.status == "open"),
        # Regardless of suggestion_status — needing to suggest ANYTHING is
        # an input-quality signal whether or not the PM later accepted it.
        "suggestion_count_total": sum(1 for i in all_items if i.origin == "ai_suggestion"),
        "suggestion_accepted_count": sum(
            1 for i in all_items if i.origin == "ai_suggestion" and i.suggestion_status == "accepted"
        ),
        "policy_derived_count": sum(
            1 for i in visible_items if (i.source_reference or "").startswith(_POLICY_SOURCE_PREFIX)
        ),
    }


def _clamp(n: float, lo: int = 0, hi: int = 100) -> int:
    return int(round(max(lo, min(hi, n))))


def _synthesize_scores(
    source_clarity_score: int,
    output_specificity_score: int,
    artifact_quality_score: int,
    weak_story_ids: list[str],
    signals: dict,
) -> tuple[int, int]:
    """
    See this feature's plan (Requirements Evaluation — Dual-Agent Quality
    Scoring) for the full rationale. Each capped term's max contribution is
    documented inline so the formula stays auditable without cross-
    referencing anything external.
    """
    total_stories = max(1, signals["total_story_count"])
    weak_ratio = len(weak_story_ids) / total_stories

    # INPUT QUALITY — dominant term is the source agent's own judgment,
    # expressed as a deficit (0 = perfectly clear) so a flawless source with
    # zero downstream symptoms resolves to exactly 100, no offset hack.
    # Remaining terms are the downstream SYMPTOMS of unclear input: gaps,
    # suggestions needed, policy fallbacks used, generic stories — quantity
    # only; quality of those artifacts is an OUTPUT concern (below), not
    # evidence about the client's own material. Each capped so no single
    # runaway count alone zeroes an otherwise-clear source. Caps sum to 45;
    # deficit weight 55 -> max total penalty is exactly 100.
    clarity_deficit = 100 - source_clarity_score
    gap_penalty = min(15, signals["high_severity_gap_count"] * 3 + signals["gap_count"] * 1)
    suggestion_penalty = min(12, signals["suggestion_count_total"] * 2)
    policy_penalty = min(10, signals["policy_derived_count"] * 4)
    genericness_penalty = min(8, weak_ratio * 16)
    input_quality_score = _clamp(
        100 - 0.55 * clarity_deficit - gap_penalty - suggestion_penalty - policy_penalty - genericness_penalty
    )

    # OUTPUT QUALITY — how well did the SYSTEM do, independent of how much
    # was needed. Blends story specificity (60%) with the quality of the
    # advisory artifacts it produced — gaps/suggestions/policy stories
    # (40%) — since both are things the pipeline itself produced, not facts
    # about the client's material. Lightly pulled down by currently-OPEN
    # high-severity gaps (live risk in today's deliverable) and the
    # weak-story ratio itself.
    open_high_sev_penalty = min(15, signals["open_high_severity_gap_count"] * 5)
    genericness_output_penalty = min(10, weak_ratio * 20)
    output_quality_score = _clamp(
        0.6 * output_specificity_score
        + 0.4 * artifact_quality_score
        - open_high_sev_penalty
        - genericness_output_penalty
    )

    return input_quality_score, output_quality_score


def _build_recommendations(signals: dict, weak_story_ids: list[str]) -> list[str]:
    recs: list[str] = []
    if signals["open_gap_count"] > 0:
        n = signals["open_gap_count"]
        recs.append(f"{n} open gap{'s' if n != 1 else ''} — resolve or dismiss before approving.")
    pending_ish = signals["suggestion_count_total"] - signals["suggestion_accepted_count"]
    if pending_ish > 0:
        recs.append(
            f"{pending_ish} AI suggestion{'s' if pending_ish != 1 else ''} not yet accepted — "
            "review the Suggestions panel."
        )
    if weak_story_ids:
        ids = ", ".join(weak_story_ids[:5])
        more = f" (+{len(weak_story_ids) - 5} more)" if len(weak_story_ids) > 5 else ""
        recs.append(f"{len(weak_story_ids)} generic/weak stories flagged: {ids}{more} — tighten before relying on them.")
    return recs


_MAX_FINDINGS_PER_CATEGORY = 5
_MAX_WEAK_ITEMS_DISPLAYED = 5

# Matches the category labels the frontend uses to pick a Badge tone per
# card — keep these three literal strings in sync with EvaluationPanel.tsx's
# CATEGORY_TONE map if either side changes.
_CATEGORY_SOURCE = "Source material"
_CATEGORY_STORIES = "Stories"
_CATEGORY_ADVISORY = "Advisory content"


def _build_key_findings(
    source_issues: list[str], story_weak_items: list[dict], artifact_issues: list[str]
) -> list[dict]:
    """
    Each finding keeps which review agent raised it — the categories
    correspond directly to what a PM can go trace it against on this same
    page (the source document, the epic/story tree, or the Gaps/
    Suggestions/Policies content). Capped per category (defense in depth,
    not just the prompt instructions each agent already follows — an LLM
    isn't a guaranteed-compliant rate limiter, confirmed directly when a
    live run once listed all 8 weak stories individually with near-
    identical wording despite being asked for a consolidated list).
    """
    findings: list[dict] = []
    for issue in source_issues[:_MAX_FINDINGS_PER_CATEGORY]:
        findings.append({"category": _CATEGORY_SOURCE, "text": issue})
    for w in story_weak_items[:_MAX_WEAK_ITEMS_DISPLAYED]:
        findings.append({"category": _CATEGORY_STORIES, "text": f"{w['external_id']}: {w['reason']}"})
    for issue in artifact_issues[:_MAX_FINDINGS_PER_CATEGORY]:
        findings.append({"category": _CATEGORY_ADVISORY, "text": issue})

    seen: set[tuple[str, str]] = set()
    deduped = []
    for f in findings:
        key = (f["category"], f["text"])
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


def run_evaluation(session: Session, document: Document, llm_client, model: str) -> EvaluationReport:
    """
    Runs (or re-runs) the on-demand evaluation for `document`'s CURRENT
    visible tree — an explicit PM action (POST .../evaluate), never run
    automatically. UPSERTs the single evaluation_reports row for this
    document_id: a point-in-time snapshot of the current version, not a
    history log — re-running replaces it.
    """
    all_items = session.query(RequirementItem).filter(RequirementItem.document_id == document.id).all()
    # Matches _detail_for's own visible-tree definition exactly (None or
    # "accepted") — deliberately NOT requirements_extraction.py's
    # _build_final_data, which excludes even accepted suggestions for its
    # own different purpose (suggestion-dedup "what already exists" check).
    visible_items = [i for i in all_items if i.suggestion_status in (None, "accepted")]
    gaps = session.query(Gap).filter(Gap.document_id == document.id).all()

    if document.source_file_path:
        source_text = extract_text(Path(document.source_file_path))
    else:
        source_text = build_staged_extraction_text(session, document.project_id)

    epics_payload, stories_payload = _build_story_review_payload(visible_items)
    gaps_payload, suggestions_payload, policy_stories_payload = _build_artifact_review_payload(
        all_items, visible_items, gaps
    )

    with ThreadPoolExecutor(max_workers=3) as pool:
        source_future = pool.submit(review_source_material, source_text, llm_client, model)
        output_future = pool.submit(review_output_stories, epics_payload, stories_payload, llm_client, model)
        artifact_future = pool.submit(
            review_advisory_artifacts, gaps_payload, suggestions_payload, policy_stories_payload, llm_client, model
        )
        clarity_score, input_summary, source_issues, source_usage = source_future.result()
        specificity_score, output_summary, weak_items, output_usage = output_future.result()
        artifact_score, artifact_summary, artifact_issues, artifact_usage = artifact_future.result()

    signals = _compute_signals(all_items, visible_items, gaps)
    weak_story_ids = [w["external_id"] for w in weak_items]
    input_score, output_score = _synthesize_scores(
        clarity_score, specificity_score, artifact_score, weak_story_ids, signals
    )

    report = session.query(EvaluationReport).filter(EvaluationReport.document_id == document.id).first()
    if report is None:
        report = EvaluationReport(document_id=document.id)
        session.add(report)
    report.input_quality_score = input_score
    report.output_quality_score = output_score
    report.input_summary = input_summary
    report.output_summary = f"{output_summary} {artifact_summary}".strip()
    report.key_findings = _build_key_findings(source_issues, weak_items, artifact_issues)
    report.recommendations = _build_recommendations(signals, weak_story_ids)
    report.signals = signals
    report.weak_story_ids = weak_story_ids
    # The three agents' own raw scores, kept alongside the two blended
    # headline scores — shown per-category in the UI.
    report.source_material_score = clarity_score
    report.stories_score = specificity_score
    report.advisory_content_score = artifact_score

    log_ai_call(session, document, model, source_usage, call_type="source_material_review")
    log_ai_call(session, document, model, output_usage, call_type="output_story_review")
    log_ai_call(session, document, model, artifact_usage, call_type="artifact_quality_review")
    session.flush()
    return report
