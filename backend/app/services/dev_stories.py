"""
dev_stories.py
The development module: approved user stories -> development stories (Jira
Stories) -> technical tasks (Jira Sub-tasks) with a coding prompt each.

- The tech profile is the project's own stack per area, typed in or read from an
  uploaded document. Areas left empty make the coding prompts recommend options.
- Development stories are planned per epic from the latest approved requirements
  version (dev_story_generator.py, GPT-4o).
- Each task's coding prompt is written by Claude on Bedrock
  (coding_prompt_generator.py) with the full context: stack, company standards,
  the user story, sibling tasks, story dependencies and designed screens.

Everything here is advisory until a person sends it to Jira.
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from ai.text.coding_prompt_generator import generate_coding_prompt
from ai.text.dev_story_generator import TECH_AREAS, _format_user_story, generate_dev_stories, read_tech_profile
from ai.text.document_text import extract_text
from config import (
    CODING_PROMPT_INPUT_COST_PER_MILLION,
    CODING_PROMPT_MODEL,
    CODING_PROMPT_OUTPUT_COST_PER_MILLION,
    CODING_PROMPT_TECH_DOCUMENT_CHARS,
    DEV_STORY_MODEL,
    GPT4O_INPUT_COST_PER_MILLION,
    GPT4O_OUTPUT_COST_PER_MILLION,
    TECH_PROFILE_MAX_DOCUMENT_CHARS,
    TECH_PROFILE_MODEL,
)

from ..db.models import AiCall, DevStory, DevTask, Document, Project, RequirementItem, StandingPolicy
from .ux_prompts import (
    _epic_dict,
    _ordered_items,
    _story_dict,
    dependency_map,
    latest_approved_document,
    order_epics,
    screen_registry,
)

_TEXT_SUFFIXES = {".txt", ".md"}
_DOCUMENT_SUFFIXES = {".pdf", ".docx"} | _TEXT_SUFFIXES


def _gpt_cost(usage) -> float:
    return (
        usage.prompt_tokens * GPT4O_INPUT_COST_PER_MILLION + usage.completion_tokens * GPT4O_OUTPUT_COST_PER_MILLION
    ) / 1_000_000


def _claude_cost(usage) -> float:
    return (
        usage.prompt_tokens * CODING_PROMPT_INPUT_COST_PER_MILLION
        + usage.completion_tokens * CODING_PROMPT_OUTPUT_COST_PER_MILLION
    ) / 1_000_000


def _log_call(session: Session, project_id: str, document_id: Optional[str], call_type: str, model: str, usage, cost: float):
    session.add(
        AiCall(
            document_id=document_id,
            project_id=project_id,
            call_type=call_type,
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            estimated_cost_usd=cost,
        )
    )


# ── Tech profile ─────────────────────────────────────────────────────────────

def get_tech_profile(project: Project) -> dict[str, Any]:
    profile = dict(project.tech_profile or {})
    areas = {key: (profile.get("areas") or {}).get(key, "") for key in TECH_AREAS}
    return {
        "areas": areas,
        "document_name": profile.get("document_name"),
        "document_chars": len(profile.get("document_text") or ""),
    }


def unspecified_areas(project: Project) -> list[str]:
    return [key for key, value in get_tech_profile(project)["areas"].items() if not value.strip()]


def save_tech_profile(session: Session, project: Project, areas: dict[str, str]) -> dict[str, Any]:
    profile = dict(project.tech_profile or {})
    profile["areas"] = {key: (areas.get(key) or "").strip() for key in TECH_AREAS}
    project.tech_profile = profile
    session.flush()
    return get_tech_profile(project)


def read_tech_document(session: Session, project: Project, filename: str, data: bytes, llm_client) -> dict[str, Any]:
    """Stores the uploaded document's text on the profile and returns the areas
    the AI read from it (not saved: the person reviews them, then saves)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _DOCUMENT_SUFFIXES:
        raise ValueError("Upload the tech stack as a PDF, Word (.docx), Markdown or text file.")
    if suffix in _TEXT_SUFFIXES:
        text = data.decode("utf-8", errors="replace")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"upload{suffix}"
            path.write_bytes(data)
            text = extract_text(path)
    text = text.strip()[:TECH_PROFILE_MAX_DOCUMENT_CHARS]
    if not text:
        raise ValueError("No text could be read from that file.")

    proposed, usage = read_tech_profile(text, llm_client)
    _log_call(session, project.id, None, "tech_profile", TECH_PROFILE_MODEL, usage, _gpt_cost(usage))

    profile = dict(project.tech_profile or {})
    profile["document_name"] = filename
    profile["document_text"] = text
    project.tech_profile = profile
    session.flush()
    current = get_tech_profile(project)["areas"]
    # What the document says fills empty areas; anything already typed stays.
    merged = {key: current[key] or proposed.get(key, "") for key in TECH_AREAS}
    return {"areas": merged, "read_from_document": proposed, "document_name": filename, "document_chars": len(text)}


# ── Overview ─────────────────────────────────────────────────────────────────

def task_out(task: DevTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "position": task.position,
        "title": task.title,
        "summary": task.summary,
        "area": task.area,
        "coding_prompt": task.coding_prompt,
        "edited_prompt": task.edited_prompt,
        "tech_decision_needed": task.tech_decision_needed,
        "decision_areas": task.decision_areas or [],
        "prompt_generated_at": task.prompt_generated_at,
        "screens": task.screens or [],
        "jira_key": task.jira_key,
        "jira_url": task.jira_url,
    }


def _story_out(story: DevStory, tasks: list[DevTask], current_doc_id: Optional[str]) -> dict[str, Any]:
    return {
        "id": story.id,
        "epic_external_id": story.epic_external_id,
        "source_story_external_id": story.source_story_external_id,
        "position": story.position,
        "title": story.title,
        "description": story.description,
        "acceptance_criteria": story.acceptance_criteria or [],
        "story_points": story.story_points,
        "labels": story.labels or [],
        "jira_key": story.jira_key,
        "jira_url": story.jira_url,
        "is_stale": story.document_id != current_doc_id,
        "tasks": [task_out(t) for t in sorted(tasks, key=lambda t: t.position)],
    }


def overview(session: Session, project: Project) -> dict[str, Any]:
    doc = latest_approved_document(session, project.id)
    result: dict[str, Any] = {
        "document": doc,
        "tech_profile": get_tech_profile(project),
        "unspecified_areas": unspecified_areas(project),
        "epics": [],
    }
    if doc is None:
        return result

    items = _ordered_items(session, doc.id)
    epics = [i for i in items if i.type == "epic"]
    stories_by_epic: dict[str, list[RequirementItem]] = {}
    for item in items:
        if item.type == "story" and item.parent_id:
            stories_by_epic.setdefault(item.parent_id, []).append(item)

    dev_stories = (
        session.query(DevStory).filter(DevStory.project_id == project.id).order_by(DevStory.position).all()
    )
    tasks_by_story: dict[str, list[DevTask]] = {}
    if dev_stories:
        for task in session.query(DevTask).filter(DevTask.dev_story_id.in_([s.id for s in dev_stories])).all():
            tasks_by_story.setdefault(task.dev_story_id, []).append(task)

    stored = dependency_map(doc) or {}
    order = order_epics([e.external_id for e in epics], stored.get("feature_map") or [])
    by_external = {e.external_id: e for e in epics}
    for external_id in order:
        epic = by_external[external_id]
        mine = [s for s in dev_stories if s.epic_external_id == external_id]
        result["epics"].append(
            {
                "external_id": external_id,
                "title": epic.text,
                "stories": [
                    {"id": s.id, "external_id": s.external_id, "title": s.text}
                    for s in stories_by_epic.get(epic.id, [])
                ],
                "dev_stories": [_story_out(s, tasks_by_story.get(s.id, []), doc.id) for s in mine],
            }
        )
    return result


# ── Generating development stories ──────────────────────────────────────────

def _markdown_description(planned: dict[str, Any]) -> str:
    parts = [planned["objective"].strip()]
    if planned.get("scope"):
        parts.append("**Scope**\n" + "\n".join(f"- {line}" for line in planned["scope"]))
    return "\n\n".join(parts)


def generate_for_epic(session: Session, project: Project, epic_external_id: str, llm_client) -> list[DevStory]:
    """Plans the development stories of one epic from the latest approved version,
    replacing that epic's earlier plan. Refuses while any of the earlier plan is in
    Jira: sending again is what updates those (it would otherwise duplicate them)."""
    doc = latest_approved_document(session, project.id)
    if doc is None:
        raise ValueError("Approve a requirements version first — development stories come from approved stories.")
    items = _ordered_items(session, doc.id)
    epic = next((i for i in items if i.type == "epic" and i.external_id == epic_external_id), None)
    if epic is None:
        raise LookupError(f"Epic {epic_external_id} is not in the approved version.")
    stories = [i for i in items if i.type == "story" and i.parent_id == epic.id]
    if not stories:
        raise ValueError(f"Epic {epic_external_id} has no approved stories to plan.")

    existing = (
        session.query(DevStory)
        .filter(DevStory.project_id == project.id, DevStory.epic_external_id == epic_external_id)
        .all()
    )
    existing_ids = [s.id for s in existing]
    sent = [s for s in existing if s.jira_key] + (
        session.query(DevTask).filter(DevTask.dev_story_id.in_(existing_ids), DevTask.jira_key.isnot(None)).all()
        if existing_ids
        else []
    )
    if sent:
        raise ValueError(
            f"Some of epic {epic_external_id}'s development stories are already in Jira. Edit them here and send "
            "again to update Jira, instead of planning the epic from scratch."
        )

    planned, usage = generate_dev_stories(_epic_dict(epic), [_story_dict(s) for s in stories], llm_client)
    _log_call(session, project.id, doc.id, "dev_story", DEV_STORY_MODEL, usage, _gpt_cost(usage))

    if existing_ids:
        session.query(DevTask).filter(DevTask.dev_story_id.in_(existing_ids)).delete(synchronize_session=False)
        session.query(DevStory).filter(DevStory.id.in_(existing_ids)).delete(synchronize_session=False)

    story_by_external = {s.external_id: s for s in stories}
    created: list[DevStory] = []
    for position, plan in enumerate(planned):
        source = story_by_external[plan["source_story"]]
        dev = DevStory(
            project_id=project.id,
            document_id=doc.id,
            epic_item_id=epic.id,
            source_story_item_id=source.id,
            epic_external_id=epic.external_id,
            source_story_external_id=source.external_id,
            position=position,
            title=plan["title"].strip(),
            description=_markdown_description(plan),
            acceptance_criteria=[c.strip() for c in plan["acceptance_criteria"] if c.strip()],
            story_points=plan["story_points"],
            labels=[label.strip() for label in plan["labels"] if label.strip()],
        )
        session.add(dev)
        session.flush()
        for task_position, task in enumerate(plan["tasks"]):
            session.add(
                DevTask(
                    dev_story_id=dev.id,
                    position=task_position,
                    title=task["title"].strip(),
                    summary=task["summary"].strip(),
                    area=task["area"],
                    tech_decision_needed=False,
                    decision_areas=[],
                    screens=[],
                )
            )
        created.append(dev)
    session.flush()
    return created


# ── Coding prompts ───────────────────────────────────────────────────────────

def _get_task(session: Session, project: Project, task_id: str) -> tuple[DevTask, DevStory]:
    row = (
        session.query(DevTask, DevStory)
        .join(DevStory, DevStory.id == DevTask.dev_story_id)
        .filter(DevTask.id == task_id, DevStory.project_id == project.id)
        .first()
    )
    if row is None:
        raise LookupError(f"Task {task_id} not found")
    return row


def _get_story(session: Session, project: Project, story_id: str) -> DevStory:
    story = session.query(DevStory).filter(DevStory.id == story_id, DevStory.project_id == project.id).first()
    if story is None:
        raise LookupError(f"Development story {story_id} not found")
    return story


def coding_prompt_context(session: Session, project: Project, task: DevTask, dev: DevStory) -> dict[str, Any]:
    """Everything the coding prompt is written from — see coding_prompt_generator.build_request."""
    document = session.get(Document, dev.document_id)
    items = _ordered_items(session, document.id)
    epic = next(i for i in items if i.id == dev.epic_item_id)
    source = next((i for i in items if i.id == dev.source_story_item_id), None)
    stories_by_external = {i.external_id: i for i in items if i.type == "story"}

    profile = project.tech_profile or {}
    siblings = (
        session.query(DevTask)
        .filter(DevTask.dev_story_id == dev.id, DevTask.id != task.id)
        .order_by(DevTask.position)
        .all()
    )
    needs = []
    stored = dependency_map(document) or {}
    for dep in stored.get("story_dependencies", []):
        if source is not None and dep["story_external_id"] == source.external_id:
            target = stories_by_external.get(dep["depends_on"])
            title = target.text if target is not None else ""
            why = f" ({dep['reason']})" if dep.get("reason") else ""
            needs.append(f"{source.external_id} needs {dep['depends_on']} {title}{why}")

    screens = [
        f"{s['name']} ({s['route']})" + (f" - {s['purpose']}" if s.get("purpose") else "")
        for s in screen_registry(session, project.id)
        if s["owner"] == epic.external_id
    ]
    standards = [
        {"title": p.title, "text": p.policy_text}
        for p in session.query(StandingPolicy).filter(StandingPolicy.is_active.is_(True)).all()
    ]
    return {
        "project_name": project.name,
        "vision": ((project.style_brief or {}).get("vision") or "").strip(),
        "tech_areas": get_tech_profile(project)["areas"],
        "tech_document_excerpt": (profile.get("document_text") or "")[:CODING_PROMPT_TECH_DOCUMENT_CHARS],
        "standards": standards,
        "epic": _epic_dict(epic),
        "user_story_text": _format_user_story(_story_dict(source)) if source is not None else dev.title,
        "dev_story": {
            "title": dev.title,
            "description": dev.description,
            "acceptance_criteria": dev.acceptance_criteria or [],
        },
        "task": {"title": task.title, "summary": task.summary, "area": task.area},
        "sibling_tasks": [{"title": t.title, "summary": t.summary, "area": t.area} for t in siblings],
        "story_dependencies": needs,
        "screens": screens,
    }


def write_coding_prompt(session: Session, project: Project, task_id: str, coding_client) -> DevTask:
    """(Re)writes a task's coding prompt. Discards earlier edits — the page asks first."""
    task, dev = _get_task(session, project, task_id)
    context = coding_prompt_context(session, project, task, dev)
    data, usage = generate_coding_prompt(context, coding_client)
    _log_call(session, project.id, dev.document_id, "coding_prompt", CODING_PROMPT_MODEL, usage, _claude_cost(usage))
    task.coding_prompt = data["prompt_markdown"].strip()
    task.edited_prompt = None
    task.tech_decision_needed = data["tech_decision_needed"]
    task.decision_areas = data["decision_areas"]
    task.prompt_generated_at = datetime.now(timezone.utc)
    session.flush()
    return task


# ── Editing ──────────────────────────────────────────────────────────────────

_STORY_FIELDS = ("title", "description", "acceptance_criteria", "story_points", "labels")
_TASK_FIELDS = ("title", "summary", "area", "edited_prompt")


def update_story(session: Session, project: Project, story_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    story = _get_story(session, project, story_id)
    for field in _STORY_FIELDS:
        if field in changes:
            setattr(story, field, changes[field])
    session.flush()
    tasks = session.query(DevTask).filter(DevTask.dev_story_id == story.id).all()
    current = latest_approved_document(session, project.id)
    return _story_out(story, tasks, current.id if current else None)


def update_task(session: Session, project: Project, task_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    task, _dev = _get_task(session, project, task_id)
    for field in _TASK_FIELDS:
        if field in changes:
            value = changes[field]
            if field == "edited_prompt" and value is not None and value.strip() == (task.coding_prompt or "").strip():
                value = None  # identical to the generated text: not an edit
            setattr(task, field, value)
    session.flush()
    return task_out(task)


def delete_story(session: Session, project: Project, story_id: str) -> None:
    story = _get_story(session, project, story_id)
    session.query(DevTask).filter(DevTask.dev_story_id == story.id).delete(synchronize_session=False)
    session.delete(story)
    session.flush()


def delete_task(session: Session, project: Project, task_id: str) -> None:
    task, _dev = _get_task(session, project, task_id)
    session.delete(task)
    session.flush()
