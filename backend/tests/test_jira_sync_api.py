"""
HTTP-level tests for sending development stories to Jira. Jira is faked: it
records what would be created, updated and attached, and can be told to
refuse an issue, drop the connection or reject a description as too long.
Planning and coding prompts reuse the fakes from test_dev_stories_api.
"""
import json

import pytest
import requests

from app.db.models import AlignmentFinding, AlignmentReport, Document, RequirementItem
from app.db.session import get_session
from app.deps import get_jira_client
from app.main import app
from app.services import jira_sync
from app.services.jira_adf import markdown_to_adf
from app.services.jira_client import JiraError
from tests.test_dev_stories_api import _seed, client, claude_fake, openai_fake, project_id  # noqa: F401  (fixtures)


class FakeJira:
    base_url = "https://tk-mind.atlassian.net"

    def __init__(self):
        self.issues: dict[str, dict] = {}
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict, dict | None]] = []
        self.attachments: list[tuple[str, str, int]] = []
        self.next_id = 100
        self.refuse = None  # fields -> exception to raise on create, or None
        self.project = {
            "id": "10001",
            "key": "TK",
            "name": "TKMiND Platform",
            "issueTypes": [
                {"id": "1", "name": "Epic", "hierarchyLevel": 1, "subtask": False},
                {"id": "2", "name": "Story", "hierarchyLevel": 0, "subtask": False},
                {"id": "3", "name": "Task", "hierarchyLevel": 0, "subtask": False},
                {"id": "4", "name": "Subtask", "hierarchyLevel": -1, "subtask": True},
            ],
        }
        self.fields = {"2": [{"fieldId": "customfield_10016", "name": "Story point estimate", "required": False}]}

    def browse_url(self, key):
        return f"{self.base_url}/browse/{key}"

    def get_project(self, key):
        if key != "TK":
            raise JiraError(404, '{"errorMessages":["No project could be found with key"]}')
        return self.project

    def create_fields(self, key, issue_type_id):
        return self.fields.get(issue_type_id, [])

    def create_issue(self, fields):
        if self.refuse:
            problem = self.refuse(fields)
            if problem:
                raise problem
        key = f"TK-{self.next_id}"
        self.next_id += 1
        self.issues[key] = {"fields": fields, "labels": set(fields.get("labels") or [])}
        self.created.append({"key": key, **fields})
        return {"key": key, "id": key}

    def update_issue(self, key, fields, update=None):
        if key not in self.issues:
            raise JiraError(404, '{"errorMessages":["Issue does not exist or you do not have permission to see it."]}')
        if self.refuse and fields.get("description"):
            problem = self.refuse(fields)
            if problem:
                raise problem
        self.updated.append((key, fields, update))
        self.issues[key]["fields"].update(fields)
        for op in (update or {}).get("labels", []):
            if "add" in op:
                self.issues[key]["labels"].add(op["add"])
            if "remove" in op:
                self.issues[key]["labels"].discard(op["remove"])

    def add_attachment(self, key, filename, content, media_type):
        self.attachments.append((key, filename, len(content)))
        return {"id": f"att-{len(self.attachments)}", "filename": filename}

    def by_type(self, type_id):
        return [c for c in self.created if c.get("issuetype", {}).get("id") == type_id]


@pytest.fixture
def jira():
    fake = FakeJira()
    app.dependency_overrides[get_jira_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_jira_client, None)


def _plan_e1(client, project_id):
    r = client.post(f"/projects/{project_id}/dev-stories/epics/E1/generate")
    assert r.status_code == 200, r.text
    return r.json()


def _connect(client, project_id, key="tk"):
    return client.put(f"/projects/{project_id}/dev-stories/jira/settings", json={"project_key": key})


def _send(client, project_id, epic="E1"):
    r = client.post(f"/projects/{project_id}/dev-stories/jira/epics/{epic}/send")
    assert r.status_code == 200, r.text
    return r.json()


def _preview(client, project_id):
    r = client.get(f"/projects/{project_id}/dev-stories/jira")
    assert r.status_code == 200, r.text
    return r.json()


def _seed_design(project_id, req_doc_id, tmp_path, monkeypatch):
    """Screens: p1 aligned to S1; p2 partial from an older check (no link kept, a
    finding on S2); p3 aligned from an older check (nothing to go on); p4 misaligned."""
    with get_session() as s:
        design = Document(project_id=project_id, doc_type="design", source_filename="screens.pdf",
                          checked_against_document_id=req_doc_id)
        s.add(design)
        s.flush()
        reports = [
            AlignmentReport(design_document_id=design.id, requirements_document_id=req_doc_id, page=1,
                            status="aligned", related_story_ids=["S1"]),
            AlignmentReport(design_document_id=design.id, requirements_document_id=req_doc_id, page=2,
                            status="partial", related_story_ids=None),
            AlignmentReport(design_document_id=design.id, requirements_document_id=req_doc_id, page=3,
                            status="aligned", related_story_ids=None),
            AlignmentReport(design_document_id=design.id, requirements_document_id=req_doc_id, page=4,
                            status="misaligned", related_story_ids=["S1"]),
        ]
        s.add_all(reports)
        s.flush()
        s2 = s.query(RequirementItem).filter_by(document_id=req_doc_id, external_id="S2").one()
        s.add(AlignmentFinding(alignment_report_id=reports[1].id, requirement_item_id=s2.id,
                               issue="Missing save button", recommendation="Add it"))
        design_id = design.id
    tiles = []
    for page in (1, 2, 3, 4):
        path = tmp_path / f"p{page}.png"
        path.write_bytes(b"\x89PNG fake " + bytes([page]))
        tiles.append({"page": page, "tile_path": str(path)})
    monkeypatch.setattr(jira_sync, "tiles_for_document", lambda doc_id: tiles if doc_id == design_id else [])
    return design_id


# ── Connecting ───────────────────────────────────────────────────────────────

def test_connecting_reads_the_projects_issue_types_and_story_points_field(client, project_id, jira):
    _seed(project_id)
    r = _connect(client, project_id, " tk ")

    assert r.status_code == 200, r.text
    settings = r.json()["settings"]
    assert settings["project_key"] == "TK" and settings["project_name"] == "TKMiND Platform"
    assert settings["issue_types"] == {"epic": "Epic", "story": "Story", "subtask": "Subtask"}
    assert settings["story_points_field"] == "Story point estimate"


def test_an_unknown_or_malformed_project_key_is_explained(client, project_id, jira):
    _seed(project_id)
    r = _connect(client, project_id, "NOPE")
    assert r.status_code == 422 and "No Jira project NOPE" in r.json()["detail"]
    r = _connect(client, project_id, "1-bad")
    assert r.status_code == 422 and "project key" in r.json()["detail"]


def test_a_project_without_sub_tasks_is_refused(client, project_id, jira):
    _seed(project_id)
    jira.project["issueTypes"] = [t for t in jira.project["issueTypes"] if not t["subtask"]]
    r = _connect(client, project_id)
    assert r.status_code == 422 and "Sub-task" in r.json()["detail"]


def test_sending_needs_a_connected_project(client, project_id, jira):
    _seed(project_id)
    _plan_e1(client, project_id)
    r = client.post(f"/projects/{project_id}/dev-stories/jira/epics/E1/send")
    assert r.status_code == 409 and "Connect a Jira project" in r.json()["detail"]


# ── Preview and sending ──────────────────────────────────────────────────────

def test_preview_counts_what_sending_would_do(client, project_id, jira, claude_fake, tmp_path, monkeypatch):
    doc_id = _seed(project_id)
    _seed_design(project_id, doc_id, tmp_path, monkeypatch)
    stories = _plan_e1(client, project_id)
    client.post(f"/projects/{project_id}/dev-stories/tasks/{stories[0]['tasks'][0]['id']}/coding-prompt")

    preview = _preview(client, project_id)

    assert preview["settings"] is None
    assert preview["unplanned_epics"] == 1  # E2
    (epic,) = preview["epics"]
    assert epic["external_id"] == "E1" and epic["jira_key"] is None
    assert (epic["stories"], epic["new_stories"], epic["tasks"], epic["new_tasks"]) == (2, 2, 3, 3)
    assert epic["tasks_without_prompt"] == 2 and epic["decisions_needed"] == 1
    assert epic["screens_to_attach"] == 2  # p1 on S1's frontend task, p2 on S2's
    assert preview["design"]["unlinked_screens"] == 1  # p3: aligned, from a check that didn't keep the link


def test_sending_creates_epic_stories_and_sub_tasks_with_prompts_and_screens(
    client, project_id, jira, claude_fake, tmp_path, monkeypatch
):
    doc_id = _seed(project_id)
    _seed_design(project_id, doc_id, tmp_path, monkeypatch)
    stories = _plan_e1(client, project_id)
    backend_task = stories[0]["tasks"][0]
    client.post(f"/projects/{project_id}/dev-stories/tasks/{backend_task['id']}/coding-prompt")
    assert _connect(client, project_id).status_code == 200

    result = _send(client, project_id)

    assert result["error"] is None
    assert (result["created"], result["updated"], result["attachments"]) == (6, 0, 2)
    (epic,) = jira.by_type("1")
    assert epic["summary"] == "Registration" and epic["project"] == {"key": "TK"}
    assert "S1: Register" in json.dumps(epic["description"])

    story_s1, story_s2 = jira.by_type("2")
    assert story_s1["parent"] == {"key": epic["key"]} and story_s2["parent"] == {"key": epic["key"]}
    assert story_s1["customfield_10016"] == 5
    assert story_s1["labels"] == ["registration", "frontend"]
    assert "Duplicate emails are rejected" in json.dumps(story_s1["description"])

    api, form, profile = jira.by_type("4")
    assert api["summary"] == "Build registration API" and api["parent"] == {"key": story_s1["key"]}
    assert profile["parent"] == {"key": story_s2["key"]}
    # the written prompt is the description, as Jira's document format; the decision gets a label
    assert api["description"]["content"][0] == {
        "type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Objective"}]
    }
    assert api["labels"] == ["tech-decision-needed"] and form["labels"] == []
    assert "hasn't been written yet" in json.dumps(form["description"])
    # screens: frontend sub-tasks only, the story's aligned and partial screens
    assert [(key, name) for key, name, _ in jira.attachments] == [
        (form["key"], "S1-screen-p1.png"),
        (profile["key"], "S2-screen-p2-partial.png"),
    ]
    assert "S2-screen-p2-partial.png (partly matches" in json.dumps(profile["description"])

    epic_preview = result["epic"]
    assert epic_preview["jira_key"] == epic["key"] and epic_preview["jira_url"].endswith(f"/browse/{epic['key']}")
    assert (epic_preview["new_stories"], epic_preview["new_tasks"], epic_preview["screens_to_attach"]) == (0, 0, 0)
    overview = client.get(f"/projects/{project_id}/dev-stories").json()
    assert overview["epics"][0]["dev_stories"][0]["jira_key"] == story_s1["key"]


def test_sending_again_updates_without_duplicating(client, project_id, jira, claude_fake, tmp_path, monkeypatch):
    doc_id = _seed(project_id)
    _seed_design(project_id, doc_id, tmp_path, monkeypatch)
    _plan_e1(client, project_id)
    _connect(client, project_id)
    _send(client, project_id)
    created_before = len(jira.created)

    again = _send(client, project_id)

    assert (again["created"], again["updated"], again["attachments"]) == (0, 6, 0)
    assert len(jira.created) == created_before
    story_updates = [u for u in jira.updated if "parent" in u[1] and u[1]["parent"]["key"].startswith("TK-")]
    assert story_updates and all("issuetype" not in fields for _, fields, _ in jira.updated)
    # labels are added one by one on an update, so labels people added in Jira stay
    s1_key = jira.by_type("2")[0]["key"]
    jira.issues[s1_key]["labels"].add("added-in-jira")
    _send(client, project_id)
    assert {"registration", "frontend", "added-in-jira"} <= jira.issues[s1_key]["labels"]


def test_an_issue_deleted_in_jira_is_created_again(client, project_id, jira):
    _seed(project_id)
    _plan_e1(client, project_id)
    _connect(client, project_id)
    _send(client, project_id)
    s1_key = jira.by_type("2")[0]["key"]
    del jira.issues[s1_key]

    again = _send(client, project_id)

    assert again["created"] == 1
    overview = client.get(f"/projects/{project_id}/dev-stories").json()
    assert overview["epics"][0]["dev_stories"][0]["jira_key"] not in (None, s1_key)


def test_a_refused_issue_stops_the_send_and_keeps_what_was_sent(client, project_id, jira):
    _seed(project_id)
    _plan_e1(client, project_id)
    _connect(client, project_id)
    jira.refuse = lambda f: JiraError(400, '{"errors":{"summary":"Summary is required"}}') if f.get("summary") == "Startup profile editing" else None

    first = _send(client, project_id)

    assert first["error"] == "Jira returned 400: summary: Summary is required"
    assert first["created"] == 4  # epic, S1's story and its two sub-tasks
    jira.refuse = None
    second = _send(client, project_id)
    assert second["error"] is None and second["created"] == 2 and len(jira.created) == 6


def test_a_dropped_connection_keeps_what_was_sent(client, project_id, jira):
    _seed(project_id)
    _plan_e1(client, project_id)
    _connect(client, project_id)
    jira.refuse = lambda f: requests.ConnectionError("reset") if f.get("summary") == "Profile edit screen" else None

    first = _send(client, project_id)

    assert "could not be reached" in first["error"] and first["created"] == 5
    jira.refuse = None
    assert _send(client, project_id)["created"] == 1


def test_a_prompt_too_long_for_jira_is_cut_and_attached_whole(client, project_id, jira, claude_fake):
    _seed(project_id)
    stories = _plan_e1(client, project_id)
    task = stories[0]["tasks"][0]
    long_prompt = "## Objective\nBuild it.\n\n" + "\n\n".join(f"## Part {i}\n" + "x" * 3000 for i in range(15))
    client.patch(f"/projects/{project_id}/dev-stories/tasks/{task['id']}", json={"edited_prompt": long_prompt})
    _connect(client, project_id)
    too_long = JiraError(400, '{"errors":{"description":"CONTENT_LIMIT_EXCEEDED"}}')
    jira.refuse = lambda f: too_long if len(json.dumps(f.get("description") or {})) > 32767 else None

    result = _send(client, project_id)

    assert result["error"] is None
    api = next(c for c in jira.created if c["summary"] == "Build registration API")
    assert len(json.dumps(api["description"])) <= 30000
    assert "attached as coding-prompt.md" in json.dumps(api["description"]["content"][0])
    assert [(name) for key, name, _ in jira.attachments if key == api["key"]] == ["coding-prompt.md"]
    _send(client, project_id)  # same prompt: not attached a second time
    assert [name for key, name, _ in jira.attachments if key == api["key"]] == ["coding-prompt.md"]


# ── Markdown -> Jira document format ─────────────────────────────────────────

def test_markdown_becomes_jira_document_format():
    doc = markdown_to_adf(
        "## Objective\nBuild **the** page with `fetch()` and *care*.\n\n"
        "- [ ] Step one\n  - nested detail\n- [x] Done step\n\n"
        "1. First\n2. Second\n\n"
        "```json\n{\"a\": 1}\n```\n\n"
        "| Field | Type |\n|---|---|\n| id | uuid |\n\n"
        "Keep snake_case_names and [docs](https://example.com) as they are."
    )
    heading, para, bullets, ordered, code, table, last = doc["content"]
    assert heading == {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Objective"}]}
    assert {"type": "text", "text": "the", "marks": [{"type": "strong"}]} in para["content"]
    assert {"type": "text", "text": "fetch()", "marks": [{"type": "code"}]} in para["content"]
    assert {"type": "text", "text": "care", "marks": [{"type": "em"}]} in para["content"]
    first_item = bullets["content"][0]
    assert first_item["content"][0]["content"][0]["text"] == "☐ Step one"
    assert first_item["content"][1]["type"] == "bulletList"  # nested under its item
    assert bullets["content"][1]["content"][0]["content"][0]["text"] == "☑ Done step"
    assert ordered["type"] == "orderedList" and ordered["attrs"] == {"order": 1} and len(ordered["content"]) == 2
    assert code == {"type": "codeBlock", "attrs": {"language": "json"}, "content": [{"type": "text", "text": '{"a": 1}'}]}
    assert table["content"][0]["content"][0]["type"] == "tableHeader"
    assert table["content"][1]["content"][1]["content"][0]["content"][0]["text"] == "uuid"
    assert any(n.get("text") == "Keep snake_case_names and " for n in last["content"])
    assert {"type": "text", "text": "docs", "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}]} in last["content"]

    def no_empty_text(node):
        assert node.get("type") != "text" or node["text"]
        for child in node.get("content", []):
            no_empty_text(child)

    no_empty_text(doc)
