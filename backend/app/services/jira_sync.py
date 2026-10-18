"""
jira_sync.py
Sending a project's development stories to Jira, only when a person asks:
each epic becomes a Jira Epic, its development stories Stories under it, and
their technical tasks Sub-tasks carrying the coding prompt. Frontend
sub-tasks get their user story's UI screens from the latest design check
(Validate design), as image attachments.

Sending again updates the same issues (keys are stored on dev_stories,
dev_tasks and jira_epics) and never deletes anything in Jira: a story or task
deleted here stays in Jira for the team to close. Labels are only ever added
or removed one by one, so labels people add in Jira stay.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from sqlalchemy.orm import Session

from ai.ingest.ingest import tiles_for_document
from config import JIRA_DESCRIPTION_FALLBACK_CHARS

from ..db.models import AlignmentFinding, AlignmentReport, DevStory, DevTask, Document, JiraEpic, Project, RequirementItem
from .dev_stories import overview
from .jira_adf import markdown_to_adf
from .jira_client import JiraClient, JiraError
from .ux_prompts import _ordered_items, latest_approved_document

DECISION_LABEL = "tech-decision-needed"
_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,9}$")
_STORY_POINTS_FIELDS = ("story point estimate", "story points")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def jira_error_message(e: JiraError) -> str:
    """Jira's own explanation where it gives one (errorMessages / errors)."""
    try:
        body = json.loads(e.detail)
    except (ValueError, TypeError):
        body = None
    parts: list[str] = []
    if isinstance(body, dict):
        parts.extend(str(m) for m in body.get("errorMessages") or [])
        parts.extend(f"{field}: {msg}" for field, msg in (body.get("errors") or {}).items())
    detail = "; ".join(parts) or (e.detail or "")[:300]
    if e.status_code in (401, 403):
        return f"Jira refused the Atlassian account ({e.status_code}): {detail or 'no permission'}. Check its access to the project."
    return f"Jira returned {e.status_code}: {detail}"


# ── Connecting a project ─────────────────────────────────────────────────────

def _issue_types(project: dict[str, Any]) -> dict[str, dict[str, str]]:
    types = project.get("issueTypes") or []

    def pick(match) -> Optional[dict[str, str]]:
        found = next((t for t in types if match(t)), None)
        return {"id": str(found["id"]), "name": found["name"]} if found else None

    epic = pick(lambda t: t.get("hierarchyLevel") == 1) or pick(lambda t: t.get("name", "").lower() == "epic")
    story = pick(lambda t: not t.get("subtask") and t.get("name", "").lower() == "story") or pick(
        lambda t: not t.get("subtask") and t.get("hierarchyLevel", 0) == 0 and t.get("name", "").lower() == "task"
    )
    subtask = pick(lambda t: bool(t.get("subtask")))
    missing = [name for name, found in (("Epic", epic), ("Story", story), ("Sub-task", subtask)) if not found]
    if missing:
        raise ValueError(
            f"Jira project {project.get('key')} has no {', '.join(missing)} issue type; development stories need "
            "Epic, Story (or Task) and Sub-task."
        )
    return {"epic": epic, "story": story, "subtask": subtask}


def connect(session: Session, project: Project, project_key: str, client: JiraClient) -> dict[str, Any]:
    """Checks the Jira project and remembers what sending needs: its issue types,
    the story points field and any field an Epic requires (older company-managed
    projects ask for an Epic Name)."""
    key = (project_key or "").strip().upper()
    if not _PROJECT_KEY.match(key):
        raise ValueError("Enter the Jira project key, e.g. TK (letters and digits, starting with a letter).")
    try:
        jira_project = client.get_project(key)
        types = _issue_types(jira_project)
        story_fields = client.create_fields(key, types["story"]["id"])
        epic_fields = client.create_fields(key, types["epic"]["id"])
    except JiraError as e:
        if e.status_code == 404:
            raise ValueError(f"No Jira project {key} on {client.base_url}, or the Atlassian account can't see it.")
        raise ValueError(jira_error_message(e))

    story_points = next(
        (
            {"id": f["fieldId"], "name": f["name"]}
            for name in _STORY_POINTS_FIELDS
            for f in story_fields
            if (f.get("name") or "").lower() == name
        ),
        None,
    )
    epic_name = next(
        (f["fieldId"] for f in epic_fields if (f.get("name") or "").lower() == "epic name" and f.get("required")), None
    )
    project.jira_settings = {
        "site_url": client.base_url,
        "project_key": jira_project["key"],
        "project_id": str(jira_project.get("id", "")),
        "project_name": jira_project.get("name", key),
        "issue_types": types,
        "story_points_field": story_points,
        "epic_name_field": epic_name,
        "checked_at": _now().isoformat(),
    }
    session.flush()
    return project.jira_settings


def settings_out(project: Project) -> Optional[dict[str, Any]]:
    s = project.jira_settings or {}
    if not s.get("project_key"):
        return None
    return {
        "site_url": s.get("site_url"),
        "project_key": s["project_key"],
        "project_name": s.get("project_name"),
        "issue_types": {role: t["name"] for role, t in (s.get("issue_types") or {}).items()},
        "story_points_field": (s.get("story_points_field") or {}).get("name"),
        "checked_at": s.get("checked_at"),
    }


# ── Screens from the latest design check ────────────────────────────────────

def screens_by_story(session: Session, project_id: str) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """{story external id: [{"design_document_id", "page", "status"}]} for the screens
    the latest design check judged aligned or partial, plus a summary. Checks run
    before the link was kept still tie a screen to the stories its findings name,
    which covers partial screens; aligned ones from then have nothing to go on."""
    doc = (
        session.query(Document)
        .filter(Document.project_id == project_id, Document.doc_type == "design")
        .order_by(Document.uploaded_at.desc())
        .first()
    )
    info: dict[str, Any] = {"design_document_id": None, "filename": None, "screens": 0, "unlinked_screens": 0}
    if doc is None:
        return {}, info
    reports = session.query(AlignmentReport).filter(AlignmentReport.design_document_id == doc.id).all()
    finding_rows = (
        session.query(AlignmentFinding.alignment_report_id, RequirementItem.external_id)
        .join(RequirementItem, AlignmentFinding.requirement_item_id == RequirementItem.id)
        .filter(AlignmentFinding.alignment_report_id.in_([r.id for r in reports]))
        .all()
        if reports
        else []
    )
    named: dict[str, set[str]] = {}
    for report_id, external_id in finding_rows:
        named.setdefault(report_id, set()).add(external_id)

    info.update(design_document_id=doc.id, filename=doc.source_filename, screens=len(reports))
    by_story: dict[str, list[dict[str, Any]]] = {}
    for r in sorted(reports, key=lambda r: r.page):
        if r.status == "misaligned":
            continue
        story_ids = set(r.related_story_ids or []) | named.get(r.id, set())
        if not story_ids:
            info["unlinked_screens"] += 1
            continue
        for story_id in sorted(story_ids):
            by_story.setdefault(story_id, []).append({"design_document_id": doc.id, "page": r.page, "status": r.status})
    return by_story, info


def _screens_for(task: DevTask, story: DevStory, by_story: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if task.area != "frontend" or not story.source_story_external_id:
        return []
    return by_story.get(story.source_story_external_id, [])


def _screen_filename(story: DevStory, screen: dict[str, Any]) -> str:
    suffix = "-partial" if screen["status"] == "partial" else ""
    return f"{story.source_story_external_id}-screen-p{screen['page']}{suffix}.png"


def _attached(task: DevTask, kind: str) -> list[dict[str, Any]]:
    return [a for a in task.screens or [] if a.get("kind", "screen") == kind and a.get("jira_attachment_id")]


# ── Preview ──────────────────────────────────────────────────────────────────

def preview(session: Session, project: Project) -> dict[str, Any]:
    data = overview(session, project)
    sent_epics = {e.epic_external_id: e for e in session.query(JiraEpic).filter(JiraEpic.project_id == project.id)}
    by_story, design = screens_by_story(session, project.id)
    tasks_by_id = {}
    dev_ids = [s["id"] for e in data["epics"] for s in e["dev_stories"]]
    if dev_ids:
        tasks_by_id = {t.id: t for t in session.query(DevTask).filter(DevTask.dev_story_id.in_(dev_ids))}
    stories_by_id = {s.id: s for s in session.query(DevStory).filter(DevStory.id.in_(dev_ids))} if dev_ids else {}

    epics = []
    for e in data["epics"]:
        if not e["dev_stories"]:
            continue
        sent = sent_epics.get(e["external_id"])
        tasks = [t for s in e["dev_stories"] for t in s["tasks"]]
        screens_to_attach = 0
        for s in e["dev_stories"]:
            story = stories_by_id[s["id"]]
            for t in s["tasks"]:
                task = tasks_by_id[t["id"]]
                have = {(a["design_document_id"], a["page"]) for a in _attached(task, "screen")}
                screens_to_attach += sum(
                    1 for sc in _screens_for(task, story, by_story) if (sc["design_document_id"], sc["page"]) not in have
                )
        epics.append(
            {
                "external_id": e["external_id"],
                "title": e["title"],
                "jira_key": sent.jira_key if sent else None,
                "jira_url": sent.jira_url if sent else None,
                "synced_at": sent.synced_at if sent else None,
                "stories": len(e["dev_stories"]),
                "new_stories": sum(1 for s in e["dev_stories"] if not s["jira_key"]),
                "stale_stories": sum(1 for s in e["dev_stories"] if s["is_stale"]),
                "tasks": len(tasks),
                "new_tasks": sum(1 for t in tasks if not t["jira_key"]),
                "tasks_without_prompt": sum(1 for t in tasks if not t["coding_prompt"]),
                "decisions_needed": sum(1 for t in tasks if t["tech_decision_needed"]),
                "screens_to_attach": screens_to_attach,
            }
        )
    return {
        "settings": settings_out(project),
        "design": design,
        "epics": epics,
        "unplanned_epics": sum(1 for e in data["epics"] if not e["dev_stories"]),
    }


# ── Sending ──────────────────────────────────────────────────────────────────

def _labels(values: list[str]) -> list[str]:
    """Jira labels can't contain spaces."""
    return [re.sub(r"\s+", "-", v.strip()) for v in values if v and v.strip()]


def _epic_markdown(epic: RequirementItem, stories: list[RequirementItem], doc: Document) -> str:
    lines = ["**User stories in this epic**"]
    lines.extend(f"- {s.external_id}: {s.text}" for s in stories)
    lines.append(f"\n_Sent from TKMiND: approved requirements version {doc.version}, epic {epic.external_id}._")
    return "\n".join(lines)


def _story_markdown(story: DevStory, source: Optional[RequirementItem]) -> str:
    parts = [story.description.strip()]
    if story.acceptance_criteria:
        parts.append("**Acceptance criteria**\n" + "\n".join(f"- [ ] {c}" for c in story.acceptance_criteria))
    origin = f"From user story {source.external_id}: {source.text}" if source else "From the approved requirements"
    parts.append(f"_{origin}. Technical sub-tasks carry the coding prompts._")
    return "\n\n".join(parts)


def _task_markdown(task: DevTask, screens: list[tuple[str, str]]) -> str:
    prompt = (task.edited_prompt or task.coding_prompt or "").strip()
    body = prompt or f"{task.summary}\n\n_The coding prompt hasn't been written yet; send again once it has._"
    if screens:
        lines = ["", "---", "**UI screens attached**"]
        for filename, status in screens:
            note = " (partly matches the story: see its findings on Validate design)" if status == "partial" else ""
            lines.append(f"- {filename}{note}")
        body += "\n".join(lines)
    return body


def _cut_to_fit(doc: dict[str, Any], limit: int, note: str) -> dict[str, Any]:
    """The first blocks of a document that fit in `limit` characters of JSON, after a note."""
    head = {"type": "paragraph", "content": [{"type": "text", "text": note, "marks": [{"type": "strong"}]}]}
    kept: list[dict[str, Any]] = [head]
    size = len(json.dumps(head))
    for block in doc["content"]:
        block_size = len(json.dumps(block))
        if size + block_size > limit:
            break
        kept.append(block)
        size += block_size
    return {"version": 1, "type": "doc", "content": kept}


def _too_long(e: JiraError) -> bool:
    text = (e.detail or "").lower()
    return e.status_code in (400, 413) and any(s in text for s in ("content_limit_exceeded", "too long", "exceeds", "limit"))


class _Sender:
    def __init__(self, session: Session, project: Project, client: JiraClient):
        self.session = session
        self.project = project
        self.client = client
        self.settings = project.jira_settings or {}
        self.key = self.settings["project_key"]
        self.types = self.settings["issue_types"]
        self.counts = {"created": 0, "updated": 0, "attachments": 0}

    def _upsert(
        self, existing_key: Optional[str], fields: dict[str, Any], create_only: dict[str, Any], labels: list[str]
    ) -> tuple[str, bool]:
        """(key, created). create_only holds what Jira won't take on an edit (the
        issue type, a sub-task's parent). An issue deleted in Jira since the last
        send is created again."""
        if existing_key:
            try:
                update = {"labels": [{"add": label} for label in labels]} if labels else None
                self.client.update_issue(existing_key, fields, update)
                self.counts["updated"] += 1
                return existing_key, False
            except JiraError as e:
                if e.status_code != 404:
                    raise
        created = self.client.create_issue({**fields, **create_only, "project": {"key": self.key}, "labels": labels})
        self.counts["created"] += 1
        return created["key"], True

    def epic(self, epic: RequirementItem, stories: list[RequirementItem], doc: Document) -> str:
        row = (
            self.session.query(JiraEpic)
            .filter(JiraEpic.project_id == self.project.id, JiraEpic.epic_external_id == epic.external_id)
            .first()
        )
        fields: dict[str, Any] = {
            "summary": epic.text[:255],
            "description": markdown_to_adf(_epic_markdown(epic, stories, doc)),
        }
        create_only: dict[str, Any] = {"issuetype": {"id": self.types["epic"]["id"]}}
        if self.settings.get("epic_name_field"):
            create_only[self.settings["epic_name_field"]] = epic.text[:255]
        key, _ = self._upsert(row.jira_key if row else None, fields, create_only, [])
        if row is None:
            row = JiraEpic(project_id=self.project.id, epic_external_id=epic.external_id, jira_key=key)
            self.session.add(row)
        row.jira_key = key
        row.jira_url = self.client.browse_url(key)
        row.synced_at = _now()
        self.session.flush()
        return key

    def story(self, story: DevStory, source: Optional[RequirementItem], epic_key: str) -> str:
        fields: dict[str, Any] = {
            "summary": story.title[:255],
            "description": markdown_to_adf(_story_markdown(story, source)),
            "parent": {"key": epic_key},
        }
        create_only = {"issuetype": {"id": self.types["story"]["id"]}}
        labels = _labels(story.labels or [])
        points_field = (self.settings.get("story_points_field") or {}).get("id")
        if points_field and story.story_points is not None:
            fields[points_field] = story.story_points
        try:
            key, _ = self._upsert(story.jira_key, fields, create_only, labels)
        except JiraError as e:
            # Story points can be on the create screen but not the edit screen; the story matters more.
            if not (points_field and points_field in fields and e.status_code == 400 and points_field in (e.detail or "")):
                raise
            fields.pop(points_field)
            key, _ = self._upsert(story.jira_key, fields, create_only, labels)
        story.jira_key, story.jira_url, story.jira_synced_at = key, self.client.browse_url(key), _now()
        self.session.flush()
        return key

    def task(self, task: DevTask, story: DevStory, story_key: str, screens: list[dict[str, Any]]) -> None:
        screen_files = [(_screen_filename(story, s), s["status"]) for s in screens]
        markdown = _task_markdown(task, screen_files)
        description = markdown_to_adf(markdown)
        fields: dict[str, Any] = {"summary": task.title[:255]}
        create_only = {"issuetype": {"id": self.types["subtask"]["id"]}, "parent": {"key": story_key}}
        labels = [DECISION_LABEL] if task.tech_decision_needed else []
        attach_full_prompt = False
        try:
            key, _ = self._upsert(task.jira_key, {**fields, "description": description}, create_only, labels)
        except JiraError as e:
            if not _too_long(e):
                raise
            note = "This prompt is too long for a Jira description: the full prompt is attached as coding-prompt.md."
            cut = _cut_to_fit(description, JIRA_DESCRIPTION_FALLBACK_CHARS, note)
            key, _ = self._upsert(task.jira_key, {**fields, "description": cut}, create_only, labels)
            attach_full_prompt = True
        if task.jira_key and not task.tech_decision_needed:
            try:  # the decision has been made since the last send
                self.client.update_issue(key, {}, {"labels": [{"remove": DECISION_LABEL}]})
            except JiraError:
                pass
        task.jira_key, task.jira_url, task.jira_synced_at = key, self.client.browse_url(key), _now()

        attached = list(task.screens or [])
        have = {(a.get("design_document_id"), a.get("page")) for a in _attached(task, "screen")}
        tiles = None
        for screen, (filename, _) in zip(screens, screen_files):
            if (screen["design_document_id"], screen["page"]) in have:
                continue
            if tiles is None:  # a tall screen has several tiles; the first is what Validate design shows
                tiles = {}
                for t in tiles_for_document(screen["design_document_id"]):
                    tiles.setdefault(t["page"], t["tile_path"])
            path = tiles.get(screen["page"])
            if not path or not Path(path).exists():
                continue
            created = self.client.add_attachment(key, filename, Path(path).read_bytes(), "image/png")
            attached.append({"kind": "screen", **screen, "filename": filename, "jira_attachment_id": created.get("id")})
            self.counts["attachments"] += 1
        if attach_full_prompt:
            prompt = (task.edited_prompt or task.coding_prompt or "").encode("utf-8")
            digest = hashlib.sha256(prompt).hexdigest()
            if not any(a.get("sha256") == digest for a in _attached(task, "prompt")):
                created = self.client.add_attachment(key, "coding-prompt.md", prompt, "text/markdown")
                attached.append({"kind": "prompt", "sha256": digest, "filename": "coding-prompt.md", "jira_attachment_id": created.get("id")})
                self.counts["attachments"] += 1
        task.screens = attached  # a new list, so the JSON column registers the change
        self.session.flush()


def send_epic(session: Session, project: Project, epic_external_id: str, client: JiraClient) -> dict[str, Any]:
    """Creates or updates one epic's Epic, Stories and Sub-tasks. Stops at the
    first issue Jira refuses; everything sent before it keeps its key, so
    sending again picks up where it stopped without duplicates."""
    if not (project.jira_settings or {}).get("project_key"):
        raise ValueError("Connect a Jira project on the Dev stories page first.")
    doc = latest_approved_document(session, project.id)
    if doc is None:
        raise ValueError("There is no approved requirements version.")
    items = _ordered_items(session, doc.id)
    epic = next((i for i in items if i.type == "epic" and i.external_id == epic_external_id), None)
    if epic is None:
        raise LookupError(f"No epic {epic_external_id} in the approved version.")
    dev_stories = (
        session.query(DevStory)
        .filter(DevStory.project_id == project.id, DevStory.epic_external_id == epic_external_id)
        .order_by(DevStory.position)
        .all()
    )
    if not dev_stories:
        raise ValueError(f"Plan development stories for {epic_external_id} before sending it to Jira.")

    user_stories = [i for i in items if i.type == "story" and i.parent_id == epic.id]
    source_by_external = {s.external_id: s for s in items if s.type == "story"}
    by_story, _ = screens_by_story(session, project.id)
    sender = _Sender(session, project, client)
    error = None
    try:
        epic_key = sender.epic(epic, user_stories, doc)
        for story in dev_stories:
            story_key = sender.story(story, source_by_external.get(story.source_story_external_id or ""), epic_key)
            tasks = session.query(DevTask).filter(DevTask.dev_story_id == story.id).order_by(DevTask.position).all()
            for task in tasks:
                sender.task(task, story, story_key, _screens_for(task, story, by_story))
    except JiraError as e:
        error = jira_error_message(e)
    except requests.RequestException as e:  # caught here too: raising would roll back the keys already stored
        error = f"Jira could not be reached ({e.__class__.__name__}). What was sent so far is kept; send again to continue."
    session.flush()
    epic_preview = next((e for e in preview(session, project)["epics"] if e["external_id"] == epic_external_id), None)
    return {**sender.counts, "error": error, "epic": epic_preview}
