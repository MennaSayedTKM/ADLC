"""
ux_prompts.py
Generates and manages Figma Make prompts from an approved requirements
version (see ai/text/ux_prompt_generator.py for the prompts themselves).

The model is "Lego": one Platform Blueprint prompt per project (vision, design
system, app shell, a navigation slot per epic) and then one feature prompt per
epic that snaps into its slot. Figma Make can't see the whole platform, so
every feature/edit prompt is generated with a CONTEXT PACK built here from
what the project already has — the saved design tokens, the sitemap, the
screen registry (derived from saved prompts, so it can't drift), reusable
component names, and the feature relationship map — which is how consistency
survives across prompts.

Only APPROVED versions are eligible: the approval gate is what guarantees the
stories a design is built from won't shift underneath it. Advisory only: the
PM copies the prompts; nothing is sent anywhere.
"""

import io
import re
from typing import Any, Optional

from PIL import Image
from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from ai.text.ux_prompt_generator import analyze_feature_relationships, draft_vision, generate_ux_prompt
from ai.vision.describe_screen import describe_screen
from config import (
    GPT4O_INPUT_COST_PER_MILLION,
    GPT4O_OUTPUT_COST_PER_MILLION,
    UX_PROMPT_MODEL,
    UX_PROMPT_SOFT_CHAR_LIMIT,
    UX_SCREENSHOT_DETAIL,
    UX_SCREENSHOT_MAX_TOKENS,
    UX_SCREENSHOT_MODEL,
)

from ..db.models import AiCall, Document, Project, RequirementItem, UxPrompt
from ..schemas.ux_prompts import StyleBriefIO, UxPromptOut

# Brief fields the PM edits directly. Anything else on projects.style_brief
# (sitemap, component_names, feature_map) is written by blueprint generation.
_USER_TEXT_FIELDS = (
    "vision",
    "target_users",
    "reference_brand",
    "primary_color",
    "tone",
    "appearance",
    "platform",
    "brand_notes",
)

# Caps keep the context pack small — it is re-sent with every feature prompt.
_CONTEXT_MAX_NAV = 24
_CONTEXT_MAX_SCREENS = 40
_CONTEXT_MAX_VISION_CHARS = 400
_CONTEXT_MAX_STORY_DEPS = 12


class BlueprintExistsError(ValueError):
    """A platform blueprint already exists for this project — regenerate it instead."""


# ── Logging / cost ───────────────────────────────────────────────────────────

def _estimate_cost(usage) -> float:
    input_cost = (usage.prompt_tokens / 1_000_000) * GPT4O_INPUT_COST_PER_MILLION
    output_cost = (usage.completion_tokens / 1_000_000) * GPT4O_OUTPUT_COST_PER_MILLION
    return round(input_cost + output_cost, 6)


def _log_call(session: Session, project_id: str, document_id: str, model: str, usage) -> None:
    session.add(
        AiCall(
            project_id=project_id,
            document_id=document_id,
            call_type="ux_prompt",
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            estimated_cost_usd=_estimate_cost(usage),
        )
    )


# ── Requirements tree ────────────────────────────────────────────────────────

def _ordered_items(session: Session, document_id: str) -> list[RequirementItem]:
    items = (
        session.query(RequirementItem)
        .filter(RequirementItem.document_id == document_id)
        .order_by(cast(func.substr(RequirementItem.external_id, 2), Integer))
        .all()
    )
    # Pending / dismissed AI suggestions aren't real content — same filter as
    # routers/requirements.py::_detail_for.
    return [i for i in items if i.suggestion_status in (None, "accepted")]


def latest_approved_document(session: Session, project_id: str) -> Optional[Document]:
    return (
        session.query(Document)
        .filter(
            Document.project_id == project_id,
            Document.doc_type == "requirement",
            Document.approval_status == "approved",
        )
        .order_by(Document.version.desc())
        .first()
    )


def _get_approved_document(session: Session, project: Project, document_id: str) -> Document:
    document = (
        session.query(Document)
        .filter(
            Document.id == document_id,
            Document.project_id == project.id,
            Document.doc_type == "requirement",
        )
        .first()
    )
    if document is None:
        raise LookupError(f"Requirement document {document_id} not found")
    if document.approval_status != "approved":
        raise ValueError(
            "UI/UX prompts can only be generated from an approved requirements version — "
            "approve this version first."
        )
    return document


def _num(external_id: str) -> int:
    digits = external_id[1:]
    return int(digits) if digits.isdigit() else 0


def _story_dict(story: RequirementItem) -> dict[str, Any]:
    return {
        "external_id": story.external_id,
        "title": story.text,
        "description": story.description,
        "acceptance_criteria": story.acceptance_criteria or [],
        "scenarios": story.scenarios or [],
        "error_handling": story.error_handling or [],
    }


def _epic_dict(epic: RequirementItem) -> dict[str, Any]:
    return {
        "external_id": epic.external_id,
        "title": epic.text,
        "assumptions": epic.assumptions or [],
        "dependencies": epic.dependencies or [],
    }


def _epics_with_stories(items: list[RequirementItem]) -> list[dict[str, Any]]:
    by_epic: dict[str, list[RequirementItem]] = {}
    for item in items:
        if item.type == "story" and item.parent_id:
            by_epic.setdefault(item.parent_id, []).append(item)
    return [
        {**_epic_dict(e), "stories": [_story_dict(s) for s in by_epic.get(e.id, [])]}
        for e in items
        if e.type == "epic"
    ]


def _epic_and_stories(
    session: Session, document: Document, epic_id: str, story_ids: list[str]
) -> tuple[RequirementItem, list[RequirementItem]]:
    items = {i.id: i for i in _ordered_items(session, document.id)}
    epic = items.get(epic_id)
    if epic is None or epic.type != "epic":
        raise ValueError(f"Epic {epic_id} not found in this requirements version.")
    if not story_ids:
        raise ValueError("Select at least one story.")
    stories = []
    for sid in story_ids:
        story = items.get(sid)
        if story is None or story.type != "story" or story.parent_id != epic.id:
            raise ValueError(f"Story {sid} does not belong to epic {epic.external_id}.")
        stories.append(story)
    stories.sort(key=lambda s: _num(s.external_id))  # S-number order, whatever order the client sent
    return epic, stories


# ── Style brief ──────────────────────────────────────────────────────────────

def get_style_brief(project: Project) -> dict[str, Any]:
    return dict(project.style_brief or {})


def save_style_brief(session: Session, project: Project, brief: StyleBriefIO) -> dict[str, Any]:
    """
    Applies the fields the PM sent; a field left out is left unchanged and an
    empty value clears it. Never touches the system-written keys (sitemap,
    component_names, feature_map), so saving the form can't wipe the blueprint.
    """
    sent = brief.model_fields_set
    data = brief.model_dump()
    current = get_style_brief(project)
    for key in (*_USER_TEXT_FIELDS, "reference_styles", "design_tokens_summary"):
        if key not in sent:
            continue
        if data[key]:
            current[key] = data[key]
        else:
            current.pop(key, None)
    project.style_brief = current or None
    session.flush()
    return current


def suggest_mode(document: Document, has_blueprint: bool) -> str:
    """
    Default only — the PM always picks. Until a blueprint exists the next step
    is the blueprint; a version forked from a change request is an edit to
    something already built; otherwise it is a new feature.
    """
    if not has_blueprint:
        return "foundation"
    if (document.type_metadata or {}).get("source_change_request_id"):
        return "edit_existing"
    return "new_feature"


# ── Feature relationships and ordering ───────────────────────────────────────

def _sanitize_feature_map(features: list[dict[str, Any]], epic_ids: set[str]) -> list[dict[str, Any]]:
    """depends_on comes back as [{epic, reason}]; older stored maps hold plain
    ids. Either way the result is depends_on: [ids] plus depends_on_reasons."""
    cleaned = []
    for f in features:
        eid = f.get("epic_external_id")
        if eid not in epic_ids:
            continue
        reasons: dict[str, str] = {}
        for dep in f.get("depends_on", []):
            dep_id, reason = (dep.get("epic"), dep.get("reason", "")) if isinstance(dep, dict) else (dep, "")
            if dep_id in epic_ids and dep_id != eid and dep_id not in reasons:
                reasons[dep_id] = (reason or "").strip()
        for dep_id, reason in (f.get("depends_on_reasons") or {}).items():
            if dep_id in reasons and not reasons[dep_id]:
                reasons[dep_id] = reason
        cleaned.append(
            {
                "epic_external_id": eid,
                "depends_on": list(reasons),
                "depends_on_reasons": {k: v for k, v in reasons.items() if v},
                "integrates": [
                    {"with_epic": i["with_epic"], "how": i["how"]}
                    for i in f.get("integrates", [])
                    if i.get("with_epic") in epic_ids and i["with_epic"] != eid
                ],
            }
        )
    return cleaned


def _sanitize_story_dependencies(items: list[dict[str, Any]], story_ids: set[str]) -> list[dict[str, Any]]:
    """Keeps pairs of real, different stories, once each."""
    seen: set[tuple[str, str]] = set()
    cleaned = []
    for item in items:
        pair = (item.get("story"), item.get("depends_on"))
        if pair[0] not in story_ids or pair[1] not in story_ids or pair[0] == pair[1] or pair in seen:
            continue
        seen.add(pair)
        cleaned.append(
            {"story_external_id": pair[0], "depends_on": pair[1], "reason": (item.get("reason") or "").strip()}
        )
    return cleaned


def dependency_map(document: Document) -> Optional[dict[str, Any]]:
    """The dependency map stored on an approved version, if it has one."""
    return (document.type_metadata or {}).get("dependency_map")


def compute_dependency_map(session: Session, document: Document, llm_client) -> dict[str, Any]:
    """Works out which epics and stories depend on which, for one approved
    version, and stores it on that version's type_metadata. Runs at approval
    (routers/requirements.py::approve) so the Design page can show the order
    before any blueprint exists, and on demand for versions approved earlier."""
    epics = _epics_with_stories(_ordered_items(session, document.id))
    epic_ids = {e["external_id"] for e in epics}
    story_ids = {s["external_id"] for e in epics for s in e["stories"]}
    result: dict[str, Any] = {"feature_map": [], "story_dependencies": []}
    if len(epic_ids) + len(story_ids) > 2:
        data, usage = analyze_feature_relationships(epics, llm_client, model=UX_PROMPT_MODEL)
        _log_call(session, document.project_id, document.id, UX_PROMPT_MODEL, usage)
        result = {
            "feature_map": _sanitize_feature_map(data.get("features") or [], epic_ids),
            "story_dependencies": _sanitize_story_dependencies(data.get("story_dependencies") or [], story_ids),
        }
    document.type_metadata = {**(document.type_metadata or {}), "dependency_map": result}
    session.flush()
    return result


def order_epics(epic_ids: list[str], feature_map: list[dict[str, Any]]) -> list[str]:
    """Dependencies first; E-number order among epics that are ready at the same time.
    A dependency cycle is broken by E-number order rather than failing."""
    wanted = set(epic_ids)
    deps = {e: set() for e in epic_ids}
    for f in feature_map:
        if f["epic_external_id"] in wanted:
            deps[f["epic_external_id"]] = {d for d in f.get("depends_on", []) if d in wanted}

    ordered: list[str] = []
    remaining = sorted(epic_ids, key=_num)
    while remaining:
        ready = [e for e in remaining if deps[e] <= set(ordered)]
        pick = ready[0] if ready else remaining[0]
        ordered.append(pick)
        remaining.remove(pick)
    return ordered


# ── Sitemap, registry, context pack ──────────────────────────────────────────

def _slug_route(title: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return "/" + (slug or fallback.lower())


def _normalize_sitemap(nav_items: list[dict[str, Any]], epics: list[dict[str, Any]]) -> list[dict[str, str]]:
    """One valid, unique-route slot per epic — the model's nav_items where usable,
    a title-derived fallback for any epic it missed."""
    by_epic = {n.get("epic_external_id"): n for n in nav_items}
    used: set[str] = set()
    sitemap = []
    for epic in epics:
        item = by_epic.get(epic["external_id"]) or {}
        label = (item.get("label") or epic["title"]).strip()
        route = (item.get("route") or "").strip()
        if not route.startswith("/") or route == "/":
            route = _slug_route(label, epic["external_id"])
        base, n = route, 2
        while route in used:
            route, n = f"{base}-{n}", n + 1
        used.add(route)
        sitemap.append({"epic_external_id": epic["external_id"], "label": label, "route": route})
    return sitemap


def _prompt_rows(session: Session, project_id: str, exclude_prompt_id: Optional[str] = None):
    """(prompt, epic external id or None) for every prompt of this project, oldest first."""
    query = (
        session.query(UxPrompt, RequirementItem.external_id)
        .join(Document, Document.id == UxPrompt.document_id)
        .outerjoin(RequirementItem, RequirementItem.id == UxPrompt.epic_item_id)
        .filter(Document.project_id == project_id)
        .order_by(UxPrompt.created_at)
    )
    return [(p, ext) for p, ext in query.all() if p.id != exclude_prompt_id]


def screen_registry(session: Session, project_id: str, exclude_prompt_id: Optional[str] = None) -> list[dict[str, str]]:
    """Every screen designed so far, derived from saved prompts. A later prompt's
    screen replaces an earlier one with the same route."""
    by_route: dict[str, dict[str, str]] = {}
    for prompt, epic_ext in _prompt_rows(session, project_id, exclude_prompt_id):
        for screen in prompt.screens or []:
            by_route[screen["route"]] = {
                "name": screen["name"],
                "route": screen["route"],
                "purpose": screen.get("purpose", ""),
                "owner": epic_ext or "Platform",
            }
    return list(by_route.values())


def _sitemap_with_status(session: Session, project_id: str, brief: dict[str, Any]) -> list[dict[str, str]]:
    designed = {ext for p, ext in _prompt_rows(session, project_id) if ext and p.mode != "foundation"}
    return [
        {**slot, "status": "designed" if slot["epic_external_id"] in designed else "placeholder"}
        for slot in brief.get("sitemap") or []
    ]


def _designed_story_ids(session: Session, project_id: str, exclude_prompt_id: Optional[str]) -> set[str]:
    """External ids (S4, S5...) of every story some existing prompt covers. By
    external id because a newer requirements version copies stories under new
    item ids, while the prompts keep the ids of the version they were made from."""
    item_ids = {sid for p, _ in _prompt_rows(session, project_id, exclude_prompt_id) for sid in p.story_ids or []}
    if not item_ids:
        return set()
    rows = session.query(RequirementItem.external_id).filter(RequirementItem.id.in_(item_ids)).all()
    return {r[0] for r in rows}


def build_context_pack(
    session: Session,
    project: Project,
    epic_external_id: str,
    epic_titles: dict[str, str],
    exclude_prompt_id: Optional[str] = None,
    document: Optional[Document] = None,
    story_external_ids: Optional[list[str]] = None,
) -> str:
    """
    The platform context Figma Make is given with every feature/edit prompt so
    the new piece matches what already exists. Deliberately compact: it is
    re-sent with every prompt, and Figma credits scale with prompt size.

    Dependencies come from the map stored on `document` (worked out when that
    version was approved) — the same one the Design page shows — falling back
    to the map a blueprint made before dependencies were stored per version.
    """
    brief = get_style_brief(project)
    sitemap = _sitemap_with_status(session, project.id, brief)
    registry = screen_registry(session, project.id, exclude_prompt_id)
    stored = dependency_map(document) if document is not None else None
    feature_map = stored["feature_map"] if stored is not None else brief.get("feature_map") or []
    relation = next((f for f in feature_map if f["epic_external_id"] == epic_external_id), None)
    lines: list[str] = []

    if brief.get("vision"):
        lines.append("Platform vision: " + brief["vision"].strip()[:_CONTEXT_MAX_VISION_CHARS])
    if brief.get("design_tokens_summary"):
        lines.append("Design system (reuse exactly): " + brief["design_tokens_summary"].strip())
    if brief.get("component_names"):
        lines.append("Components to reuse: " + ", ".join(brief["component_names"]))
    if sitemap:
        lines.append("Navigation:")
        for slot in sitemap[:_CONTEXT_MAX_NAV]:
            marker = "  <- THIS FEATURE" if slot["epic_external_id"] == epic_external_id else ""
            lines.append(f"- {slot['label']} -> {slot['route']} [{slot['status']}]{marker}")
    mine = next((s for s in sitemap if s["epic_external_id"] == epic_external_id), None)
    if mine:
        lines.append(f"This feature's placeholder slot: {mine['label']} -> {mine['route']} (base route for its screens)")
    if registry:
        lines.append("Screens already designed (do not change):")
        for s in registry[:_CONTEXT_MAX_SCREENS]:
            lines.append(f"- {s['name']} ({s['route']})" + (f" - {s['purpose']}" if s["purpose"] else ""))

    def screens_of(owner: str) -> str:
        names = [f"{s['name']} ({s['route']})" for s in registry if s["owner"] == owner]
        return "; ".join(names) if names else "not designed yet"

    if relation and relation["depends_on"]:
        reasons = relation.get("depends_on_reasons") or {}
        lines.append("Depends on (build on / link to these):")
        for d in relation["depends_on"]:
            why = f" ({reasons[d]})" if reasons.get(d) else ""
            lines.append(f"- {d} {epic_titles.get(d, '')}{why}: screens {screens_of(d)}")
    if relation and relation["integrates"]:
        lines.append("Integrates with:")
        for i in relation["integrates"]:
            lines.append(f"- {i['with_epic']} {epic_titles.get(i['with_epic'], '')}: {i['how']} (screens: {screens_of(i['with_epic'])})")

    # Stories in this prompt that build on another story: say where that one stands, so the
    # prompt links to existing screens, designs both together, or leaves a clear entry point.
    in_prompt = set(story_external_ids or [])
    story_deps = [d for d in (stored or {}).get("story_dependencies", []) if d["story_external_id"] in in_prompt]
    if story_deps and document is not None:
        items = _ordered_items(session, document.id)
        stories = {i.external_id: i for i in items if i.type == "story"}
        epic_of = {i.id: i.external_id for i in items if i.type == "epic"}
        designed = _designed_story_ids(session, project.id, exclude_prompt_id)
        lines.append("Story dependencies (a story builds on another one):")
        for d in story_deps[:_CONTEXT_MAX_STORY_DEPS]:
            target = stories.get(d["depends_on"])
            if target is None:
                continue
            if d["depends_on"] in in_prompt:
                where = "in this prompt - design them together"
            elif d["depends_on"] in designed:
                owner = epic_of.get(target.parent_id, "")
                where = f"already designed - link to it (screens: {screens_of(owner)})"
            else:
                where = "not designed yet - leave a clear entry point for it, don't design it here"
            why = f" ({d['reason']})" if d.get("reason") else ""
            lines.append(f"- {d['story_external_id']} needs {d['depends_on']} {target.text}{why}: {where}")
    return "\n".join(lines)


# ── Sources for the tab ──────────────────────────────────────────────────────

def get_blueprint(session: Session, project_id: str) -> Optional[UxPrompt]:
    rows = [p for p, _ in _prompt_rows(session, project_id) if p.mode == "foundation"]
    return rows[-1] if rows else None


def list_sources(session: Session, project: Project) -> dict[str, Any]:
    doc = latest_approved_document(session, project.id)
    brief = get_style_brief(project)
    blueprint = get_blueprint(session, project.id)
    result: dict[str, Any] = {
        "document": doc,
        "epics": [],
        "suggested_mode": "foundation",
        "has_blueprint": blueprint is not None,
        "blueprint_prompt_id": blueprint.id if blueprint else None,
        "epics_missing_from_blueprint": [],
        "has_design_system": bool(brief.get("design_tokens_summary")),
        "feature_map": brief.get("feature_map") or [],
        "story_dependencies": [],
        "has_dependency_map": False,
        "suggested_order": [],
        "sitemap": _sitemap_with_status(session, project.id, brief),
        "registry": screen_registry(session, project.id),
        "style_brief": brief,
        "soft_char_limit": UX_PROMPT_SOFT_CHAR_LIMIT,
    }
    if doc is None:
        return result

    # The version's own map (worked out at approval) wins; a blueprint made
    # before dependencies were stored per version still has one on the brief.
    stored = dependency_map(doc)
    if stored is not None:
        result["feature_map"] = stored["feature_map"]
        result["story_dependencies"] = stored["story_dependencies"]
        result["has_dependency_map"] = True
    else:
        result["has_dependency_map"] = bool(result["feature_map"])

    items = _ordered_items(session, doc.id)
    stories_by_epic: dict[str, list[RequirementItem]] = {}
    for item in items:
        if item.type == "story" and item.parent_id:
            stories_by_epic.setdefault(item.parent_id, []).append(item)
    epics = [i for i in items if i.type == "epic"]
    result["epics"] = [{"epic": e, "stories": stories_by_epic.get(e.id, [])} for e in epics]
    epic_ids = [e.external_id for e in epics]
    result["suggested_order"] = order_epics(epic_ids, result["feature_map"])
    result["suggested_mode"] = suggest_mode(doc, blueprint is not None)
    in_sitemap = {s["epic_external_id"] for s in result["sitemap"]}
    result["epics_missing_from_blueprint"] = [e for e in epic_ids if blueprint is not None and e not in in_sitemap]
    return result


def draft_platform_vision(session: Session, project: Project, llm_client) -> dict[str, str]:
    """AI-drafted vision from the approved requirements. Not saved — the PM edits and saves it."""
    doc = latest_approved_document(session, project.id)
    if doc is None:
        raise ValueError("Approve a requirements version first — the vision is drafted from its stories.")
    epics = _epics_with_stories(_ordered_items(session, doc.id))
    drafted, usage = draft_vision(epics, llm_client, model=UX_PROMPT_MODEL)
    _log_call(session, project.id, doc.id, UX_PROMPT_MODEL, usage)
    return drafted


# ── Generation ───────────────────────────────────────────────────────────────

def _describe_screenshot(session: Session, project_id: str, document_id: str, image_bytes: bytes, llm_client) -> str:
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as e:
        raise ValueError(f"Could not read the screenshot as an image: {e}") from e
    description, usage = describe_screen(
        image.convert("RGB"), llm_client, UX_SCREENSHOT_MODEL, UX_SCREENSHOT_DETAIL, UX_SCREENSHOT_MAX_TOKENS
    )
    _log_call(session, project_id, document_id, UX_SCREENSHOT_MODEL, usage)
    return description


def _brief_snapshot(brief: dict[str, Any], screen_description: Optional[str] = None) -> dict[str, Any]:
    snapshot = {k: brief[k] for k in _USER_TEXT_FIELDS if brief.get(k)}
    if brief.get("reference_styles"):
        snapshot["reference_styles"] = brief["reference_styles"]
    if screen_description:
        snapshot["existing_screen_description"] = screen_description
    return snapshot


def _generate_blueprint(
    session: Session, project: Project, document: Document, llm_client
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Runs the blueprint generation and stores its structured outputs (design
    tokens, sitemap, components, feature map) on the project's brief."""
    epics = _epics_with_stories(_ordered_items(session, document.id))
    if not epics:
        raise ValueError("The approved version has no epics to plan navigation slots for.")
    epic_ids = {e["external_id"] for e in epics}

    # Usually worked out already, at approval; otherwise now (and stored on the version).
    stored = dependency_map(document) or compute_dependency_map(session, document, llm_client)
    feature_map = _sanitize_feature_map(stored["feature_map"], epic_ids)

    order = order_epics([e["external_id"] for e in epics], feature_map)
    planned = sorted(epics, key=lambda e: order.index(e["external_id"]))

    brief = get_style_brief(project)
    data, usage = generate_ux_prompt(
        "foundation", brief, llm_client, model=UX_PROMPT_MODEL, planned_features=planned
    )
    _log_call(session, project.id, document.id, UX_PROMPT_MODEL, usage)

    project.style_brief = {
        **brief,
        "sitemap": _normalize_sitemap(data["nav_items"], planned),
        "component_names": data["component_names"],
        "feature_map": feature_map,
        **({"design_tokens_summary": data["design_tokens_summary"].strip()} if data["design_tokens_summary"].strip() else {}),
    }
    session.flush()
    return data, _brief_snapshot(brief)


def create_ux_prompt(
    session: Session,
    project: Project,
    document_id: str,
    mode: str,
    brief: StyleBriefIO,
    llm_client,
    epic_id: Optional[str] = None,
    story_ids: Optional[list[str]] = None,
    screenshot_bytes: Optional[bytes] = None,
) -> UxPrompt:
    document = _get_approved_document(session, project, document_id)
    # The form the PM just filled in becomes the project's saved brief.
    saved_brief = save_style_brief(session, project, brief)

    if mode == "foundation":
        if screenshot_bytes:
            raise ValueError("A screenshot can only be attached in 'edit existing' mode.")
        if get_blueprint(session, project.id) is not None:
            raise BlueprintExistsError("This project already has a platform blueprint — regenerate it instead.")
        data, snapshot = _generate_blueprint(session, project, document, llm_client)
        prompt = UxPrompt(
            document_id=document.id,
            epic_item_id=None,
            story_ids=[],
            mode="foundation",
            style_brief=snapshot,
            screens=data["screens"],
            prompt_text=data["prompt_text"].strip(),
            is_stale=False,
        )
        session.add(prompt)
        session.flush()
        return prompt

    if not epic_id:
        raise ValueError("Choose an epic.")
    epic, stories = _epic_and_stories(session, document, epic_id, list(story_ids or []))
    if mode == "new_feature" and get_blueprint(session, project.id) is None and not saved_brief.get("design_tokens_summary"):
        raise ValueError(
            "Generate the platform blueprint first — new features are built to fit it. "
            "(Or paste an existing design system summary into the style brief.)"
        )

    screen_description = None
    if screenshot_bytes:
        if mode != "edit_existing":
            raise ValueError("A screenshot can only be attached in 'edit existing' mode.")
        screen_description = _describe_screenshot(session, project.id, document.id, screenshot_bytes, llm_client)

    data = _generate_feature(session, project, document, epic, stories, mode, saved_brief, llm_client, screen_description)
    prompt = UxPrompt(
        document_id=document.id,
        epic_item_id=epic.id,
        story_ids=[s.id for s in stories],
        mode=mode,
        style_brief=_brief_snapshot(saved_brief, screen_description),
        screens=data["screens"],
        prompt_text=data["prompt_text"].strip(),
        is_stale=False,
    )
    session.add(prompt)
    session.flush()
    return prompt


def _generate_feature(
    session: Session,
    project: Project,
    document: Document,
    epic: RequirementItem,
    stories: list[RequirementItem],
    mode: str,
    brief: dict[str, Any],
    llm_client,
    screen_description: Optional[str],
    exclude_prompt_id: Optional[str] = None,
) -> dict[str, Any]:
    titles = {i.external_id: i.text for i in _ordered_items(session, document.id) if i.type == "epic"}
    context = build_context_pack(
        session, project, epic.external_id, titles, exclude_prompt_id,
        document=document, story_external_ids=[s.external_id for s in stories],
    )
    data, usage = generate_ux_prompt(
        mode,
        brief,
        llm_client,
        model=UX_PROMPT_MODEL,
        epic=_epic_dict(epic),
        stories=[_story_dict(s) for s in stories],
        context_pack=context,
        existing_screen_description=screen_description,
    )
    _log_call(session, project.id, document.id, UX_PROMPT_MODEL, usage)
    return data


def _get_prompt(session: Session, project_id: str, prompt_id: str) -> UxPrompt:
    prompt = (
        session.query(UxPrompt)
        .join(Document, Document.id == UxPrompt.document_id)
        .filter(UxPrompt.id == prompt_id, Document.project_id == project_id)
        .first()
    )
    if prompt is None:
        raise LookupError(f"UI/UX prompt {prompt_id} not found")
    return prompt


def regenerate_ux_prompt(session: Session, project: Project, prompt_id: str, llm_client) -> UxPrompt:
    """
    Re-runs a prompt. A feature/edit prompt reuses its stories, mode and
    screenshot description. The blueprint is re-run from the project's CURRENT
    brief and the latest approved version — that is how a PM adds navigation
    slots for epics approved since it was generated. Overwrites the text and
    discards PM edits (the UI confirms first).
    """
    prompt = _get_prompt(session, project.id, prompt_id)

    if prompt.mode == "foundation":
        document = latest_approved_document(session, project.id)
        if document is None:
            raise ValueError("There is no approved requirements version to regenerate from.")
        data, snapshot = _generate_blueprint(session, project, document, llm_client)
        prompt.document_id = document.id
    else:
        document = session.query(Document).filter(Document.id == prompt.document_id).first()
        epic, stories = _epic_and_stories(session, document, prompt.epic_item_id, list(prompt.story_ids))
        snapshot = dict(prompt.style_brief or {})
        brief = {**get_style_brief(project), **snapshot}
        data = _generate_feature(
            session, project, document, epic, stories, prompt.mode, brief, llm_client,
            snapshot.get("existing_screen_description"), exclude_prompt_id=prompt.id,
        )

    prompt.prompt_text = data["prompt_text"].strip()
    prompt.screens = data["screens"]
    prompt.style_brief = snapshot
    prompt.edited_text = None
    prompt.is_stale = False
    session.flush()
    return prompt


def update_edited_text(session: Session, project_id: str, prompt_id: str, edited_text: Optional[str]) -> UxPrompt:
    prompt = _get_prompt(session, project_id, prompt_id)
    # An edit identical to the generated text is no edit at all.
    prompt.edited_text = edited_text if edited_text and edited_text != prompt.prompt_text else None
    session.flush()
    return prompt


def delete_ux_prompt(session: Session, project_id: str, prompt_id: str) -> None:
    session.delete(_get_prompt(session, project_id, prompt_id))
    session.flush()


def list_ux_prompts(session: Session, project_id: str) -> list[UxPrompt]:
    return (
        session.query(UxPrompt)
        .join(Document, Document.id == UxPrompt.document_id)
        .filter(Document.project_id == project_id)
        .order_by(UxPrompt.created_at.desc())
        .all()
    )


def mark_prompts_stale(session: Session, document_id: str) -> None:
    """Called when a newer requirements version supersedes this one."""
    session.query(UxPrompt).filter(UxPrompt.document_id == document_id).update({"is_stale": True})


def to_out(session: Session, prompt: UxPrompt) -> UxPromptOut:
    ids = [i for i in [prompt.epic_item_id, *prompt.story_ids] if i]
    items = {i.id: i for i in session.query(RequirementItem).filter(RequirementItem.id.in_(ids)).all()} if ids else {}
    epic = items.get(prompt.epic_item_id) if prompt.epic_item_id else None
    return UxPromptOut(
        id=prompt.id,
        document_id=prompt.document_id,
        epic_item_id=prompt.epic_item_id,
        epic_external_id=epic.external_id if epic else None,
        epic_title=epic.text if epic else None,
        story_ids=list(prompt.story_ids),
        story_external_ids=[items[sid].external_id for sid in prompt.story_ids if sid in items],
        mode=prompt.mode,
        style_brief=prompt.style_brief,
        screens=prompt.screens or [],
        prompt_text=prompt.prompt_text,
        edited_text=prompt.edited_text,
        is_stale=prompt.is_stale,
        char_count=len(prompt.edited_text or prompt.prompt_text),
        soft_char_limit=UX_PROMPT_SOFT_CHAR_LIMIT,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
    )
