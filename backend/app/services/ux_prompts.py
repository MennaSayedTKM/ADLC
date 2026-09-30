"""
ux_prompts.py
Generates and manages Figma Make prompts from an approved requirements
version's epics and stories (see ai/text/ux_prompt_generator.py for the prompt
itself). Only APPROVED versions are eligible — the approval gate is what
guarantees the stories a design is built from won't shift underneath it.
Advisory only: the PM copies the prompt; nothing is sent anywhere.
"""

import io
from typing import Any, Optional

from PIL import Image
from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from ai.text.ux_prompt_generator import generate_ux_prompt
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

_STYLE_KEYS = (
    "reference_brand",
    "primary_color",
    "tone",
    "appearance",
    "platform",
    "brand_notes",
)


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


def get_style_brief(project: Project) -> dict[str, Any]:
    return dict(project.style_brief or {})


def save_style_brief(session: Session, project: Project, brief: StyleBriefIO) -> dict[str, Any]:
    """
    Replaces the visual fields with what the PM sent. design_tokens_summary is
    only touched if the request explicitly included it, so saving the form
    never wipes the summary a Foundation prompt produced.
    """
    updated = {k: v for k, v in brief.model_dump().items() if k in _STYLE_KEYS and v}
    current = get_style_brief(project)
    if "design_tokens_summary" in brief.model_fields_set:
        if brief.design_tokens_summary:
            updated["design_tokens_summary"] = brief.design_tokens_summary
    elif current.get("design_tokens_summary"):
        updated["design_tokens_summary"] = current["design_tokens_summary"]
    project.style_brief = updated or None
    session.flush()
    return updated


def suggest_mode(document: Document, style_brief: dict[str, Any]) -> str:
    """
    Default only — the PM always picks. A version forked from a change
    request is an edit to something built; otherwise foundation until a
    design system exists for the project, then new_feature.
    """
    if (document.type_metadata or {}).get("source_change_request_id"):
        return "edit_existing"
    return "new_feature" if style_brief.get("design_tokens_summary") else "foundation"


def list_sources(session: Session, project: Project) -> dict[str, Any]:
    doc = latest_approved_document(session, project.id)
    brief = get_style_brief(project)
    result: dict[str, Any] = {
        "document": doc,
        "epics": [],
        "suggested_mode": "foundation",
        "has_design_system": bool(brief.get("design_tokens_summary")),
        "style_brief": brief,
        "soft_char_limit": UX_PROMPT_SOFT_CHAR_LIMIT,
    }
    if doc is None:
        return result

    items = _ordered_items(session, doc.id)
    stories_by_epic: dict[str, list[RequirementItem]] = {}
    for item in items:
        if item.type == "story" and item.parent_id:
            stories_by_epic.setdefault(item.parent_id, []).append(item)
    result["epics"] = [
        {"epic": e, "stories": stories_by_epic.get(e.id, [])} for e in items if e.type == "epic"
    ]
    result["suggested_mode"] = suggest_mode(doc, brief)
    return result


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
    # Keep S-number order regardless of the order the client sent.
    stories.sort(key=lambda s: int(s.external_id[1:]) if s.external_id[1:].isdigit() else 0)
    return epic, stories


def _epic_dict(epic: RequirementItem) -> dict[str, Any]:
    return {
        "external_id": epic.external_id,
        "title": epic.text,
        "assumptions": epic.assumptions or [],
        "dependencies": epic.dependencies or [],
    }


def _story_dict(story: RequirementItem) -> dict[str, Any]:
    return {
        "external_id": story.external_id,
        "title": story.text,
        "description": story.description,
        "acceptance_criteria": story.acceptance_criteria or [],
        "scenarios": story.scenarios or [],
        "error_handling": story.error_handling or [],
    }


def _describe_screenshot(
    session: Session, project_id: str, document_id: str, image_bytes: bytes, llm_client
) -> str:
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


def _run_generation(
    session: Session,
    project: Project,
    document: Document,
    epic: RequirementItem,
    stories: list[RequirementItem],
    mode: str,
    brief: dict[str, Any],
    llm_client,
    screen_description: Optional[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (generated data, snapshot to store on the prompt row)."""
    tokens_summary = get_style_brief(project).get("design_tokens_summary")
    data, usage = generate_ux_prompt(
        mode,
        _epic_dict(epic),
        [_story_dict(s) for s in stories],
        brief,
        llm_client,
        model=UX_PROMPT_MODEL,
        design_tokens_summary=tokens_summary,
        existing_screen_description=screen_description,
    )
    _log_call(session, project.id, document.id, UX_PROMPT_MODEL, usage)

    snapshot = {k: brief[k] for k in _STYLE_KEYS if brief.get(k)}
    if screen_description:
        snapshot["existing_screen_description"] = screen_description
    snapshot["screen_names"] = data["screen_names"]
    return data, snapshot


def _remember_design_system(session: Session, project: Project, data: dict[str, Any]) -> None:
    """A Foundation prompt defines the design system — keep its compact summary
    so later new-feature / edit prompts extend it instead of reinventing it."""
    summary = (data.get("design_tokens_summary") or "").strip()
    if not summary:
        return
    project.style_brief = {**get_style_brief(project), "design_tokens_summary": summary}
    session.flush()


def create_ux_prompt(
    session: Session,
    project: Project,
    document_id: str,
    epic_id: str,
    story_ids: list[str],
    mode: str,
    brief: StyleBriefIO,
    llm_client,
    screenshot_bytes: Optional[bytes] = None,
) -> UxPrompt:
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
    epic, stories = _epic_and_stories(session, document, epic_id, story_ids)

    # The form the PM just filled in becomes the project's saved brief.
    saved_brief = save_style_brief(session, project, brief)

    screen_description = None
    if screenshot_bytes:
        if mode != "edit_existing":
            raise ValueError("A screenshot can only be attached in 'edit existing' mode.")
        screen_description = _describe_screenshot(session, project.id, document.id, screenshot_bytes, llm_client)

    data, snapshot = _run_generation(
        session, project, document, epic, stories, mode, saved_brief, llm_client, screen_description
    )
    if mode == "foundation":
        _remember_design_system(session, project, data)

    prompt = UxPrompt(
        document_id=document.id,
        epic_item_id=epic.id,
        story_ids=[s.id for s in stories],
        mode=mode,
        style_brief=snapshot,
        prompt_text=data["prompt_text"].strip(),
        is_stale=False,
    )
    session.add(prompt)
    session.flush()
    return prompt


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


def regenerate_ux_prompt(
    session: Session, project: Project, prompt_id: str, llm_client
) -> UxPrompt:
    """Re-runs the same inputs (stories, mode, style snapshot, screenshot
    description). Overwrites the text and discards any PM edits — the UI
    confirms before calling this when edited_text exists."""
    prompt = _get_prompt(session, project.id, prompt_id)
    document = session.query(Document).filter(Document.id == prompt.document_id).first()
    epic, stories = _epic_and_stories(session, document, prompt.epic_item_id, list(prompt.story_ids))

    snapshot = dict(prompt.style_brief or {})
    data, new_snapshot = _run_generation(
        session,
        project,
        document,
        epic,
        stories,
        prompt.mode,
        snapshot,
        llm_client,
        snapshot.get("existing_screen_description"),
    )
    if prompt.mode == "foundation":
        _remember_design_system(session, project, data)

    prompt.prompt_text = data["prompt_text"].strip()
    prompt.edited_text = None
    prompt.style_brief = new_snapshot
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
    items = {
        i.id: i
        for i in session.query(RequirementItem)
        .filter(RequirementItem.id.in_([prompt.epic_item_id, *prompt.story_ids]))
        .all()
    }
    epic = items[prompt.epic_item_id]
    story_external_ids = [items[sid].external_id for sid in prompt.story_ids if sid in items]
    return UxPromptOut(
        id=prompt.id,
        document_id=prompt.document_id,
        epic_item_id=prompt.epic_item_id,
        epic_external_id=epic.external_id,
        epic_title=epic.text,
        story_ids=list(prompt.story_ids),
        story_external_ids=story_external_ids,
        mode=prompt.mode,
        style_brief=prompt.style_brief,
        prompt_text=prompt.prompt_text,
        edited_text=prompt.edited_text,
        is_stale=prompt.is_stale,
        char_count=len(prompt.edited_text or prompt.prompt_text),
        soft_char_limit=UX_PROMPT_SOFT_CHAR_LIMIT,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
    )
