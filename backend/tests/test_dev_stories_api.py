"""
HTTP-level tests for development stories: the tech profile, planning
development stories and technical tasks from an approved version, and writing
each task's coding prompt. Both models are faked: OpenAI answers by tool name,
and the Claude (Bedrock) client streams back a canned Markdown answer.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from config import CODING_PROMPT_INPUT_COST_PER_MILLION, CODING_PROMPT_MODEL, CODING_PROMPT_OUTPUT_COST_PER_MILLION

from app.db.models import AiCall, DevStory, Document, RequirementItem, StandingPolicy
from app.db.session import get_session
from app.deps import get_coding_llm_client, get_openai_client
from app.main import app


def _tool_response(payload, tool_name):
    call = SimpleNamespace(function=SimpleNamespace(name=tool_name, arguments=json.dumps(payload)))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))],
        usage=SimpleNamespace(prompt_tokens=2000, completion_tokens=800),
    )


PLAN = {
    "dev_stories": [
        {
            "source_story": "S1",
            "title": "Startup registration form and account creation",
            "objective": "Let a startup register and create its account.",
            "scope": ["Registration form", "Email verification"],
            "acceptance_criteria": ["A startup can submit the form", "Duplicate emails are rejected"],
            "story_points": 5,
            "labels": ["registration", "frontend"],
            "tasks": [
                {"title": "Build registration API", "summary": "Endpoint that creates the startup account.", "area": "backend"},
                {"title": "Build registration form", "summary": "Form with validation calling the API.", "area": "frontend"},
            ],
        },
        {
            "source_story": "S2",
            "title": "Startup profile editing",
            "objective": "Let a startup keep its profile up to date.",
            "scope": [],
            "acceptance_criteria": ["Changes are saved"],
            "story_points": 3,
            "labels": ["profile"],
            "tasks": [{"title": "Profile edit screen", "summary": "Edit and save profile fields.", "area": "frontend"}],
        },
        {  # unknown story id: dropped
            "source_story": "S99",
            "title": "Invented",
            "objective": "x",
            "scope": [],
            "acceptance_criteria": [],
            "story_points": 1,
            "labels": [],
            "tasks": [{"title": "x", "summary": "x", "area": "backend"}],
        },
    ]
}


class FakeOpenAI:
    def __init__(self):
        self.client = MagicMock()
        self.client.chat.completions.create.side_effect = self._create

    def _create(self, **kwargs):
        name = kwargs["tools"][0]["function"]["name"]
        if name == "record_dev_stories":
            return _tool_response(PLAN, name)
        if name == "record_tech_profile":
            return _tool_response(
                {
                    "frontend": "Next.js 15 with TypeScript",
                    "backend": "Python 3.12 + FastAPI",
                    "database": "",
                    "infrastructure": "AWS ECS Fargate",
                    "authentication": "",
                    "integrations": "",
                    "testing": "",
                    "ci_cd": "",
                    "conventions": "",
                },
                name,
            )
        raise AssertionError(f"unexpected tool {name}")


class FakeClaude:
    """messages.stream(...) as a context manager whose get_final_message() returns the next canned answer."""

    def __init__(self):
        self.requests: list[dict] = []
        # The model answers with the Markdown itself; decisions are read from its Technology section.
        self.answer = (
            "## Objective\nBuild the registration API.\n\n"
            "## Technology\n"
            "- Backend [backend]: Python 3.12 + FastAPI\n"
            "- Database and storage [database]: **Decision needed**. Recommended: PostgreSQL 16. Alternatives: MySQL.\n"
            "- Caching [not-an-area]: **Decision needed**. Recommended: none yet.\n\n"
            "## Notes\n- Decision needed on retention is out of scope [testing].\n"
        )
        self.stop_reason = "end_turn"
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.requests.append(kwargs)
        fake = self

        class _Stream:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return SimpleNamespace(
                    content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=fake.answer)],
                    usage=SimpleNamespace(input_tokens=6000, output_tokens=3000),
                    stop_reason=fake.stop_reason,
                    stop_details=SimpleNamespace(category="cyber") if fake.stop_reason == "refusal" else None,
                )

        return _Stream()


@pytest.fixture
def openai_fake():
    fake = FakeOpenAI()
    app.dependency_overrides[get_openai_client] = lambda: fake.client
    yield fake
    app.dependency_overrides.pop(get_openai_client, None)


@pytest.fixture
def claude_fake():
    fake = FakeClaude()
    app.dependency_overrides[get_coding_llm_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_coding_llm_client, None)


@pytest.fixture
def client(openai_fake, claude_fake):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project_id(client):
    r = client.post("/projects", json={"name": f"pytest-dev-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed(project_id, approved=True, version=1):
    """One version: E1 Registration (S1, S2), E2 Funding (S3); S3 needs S1."""
    with get_session() as s:
        doc = Document(
            project_id=project_id,
            doc_type="requirement",
            version=version,
            approval_status="approved" if approved else "draft",
            source_filename="sow.pdf",
            type_metadata={
                "dependency_map": {
                    "feature_map": [{"epic_external_id": "E2", "depends_on": ["E1"], "depends_on_reasons": {}, "integrates": []}],
                    "story_dependencies": [
                        {"story_external_id": "S2", "depends_on": "S1", "reason": "edits the profile S1 creates"}
                    ],
                }
            },
        )
        s.add(doc)
        s.flush()
        e1 = RequirementItem(document_id=doc.id, type="epic", external_id="E1", text="Registration")
        e2 = RequirementItem(document_id=doc.id, type="epic", external_id="E2", text="Funding")
        s.add_all([e1, e2])
        s.flush()

        def story(ext, epic, title):
            return RequirementItem(
                document_id=doc.id, type="story", external_id=ext, parent_id=epic.id, text=title,
                description=f"As a startup, I want to {title.lower()}.",
                acceptance_criteria=[{"text": f"{title} works", "out_of_scope": False}],
            )

        s.add_all([story("S1", e1, "Register"), story("S2", e1, "Edit profile"), story("S3", e2, "Apply for funding")])
        s.flush()
        return doc.id


def _overview(client, project_id):
    r = client.get(f"/projects/{project_id}/dev-stories")
    assert r.status_code == 200, r.text
    return r.json()


def _calls(project_id, call_type):
    """(model, input tokens, output tokens, cost) of each logged call of this type."""
    with get_session() as s:
        rows = s.query(AiCall).filter(AiCall.project_id == project_id, AiCall.call_type == call_type).all()
        return [(r.model, r.input_tokens, r.output_tokens, float(r.estimated_cost_usd)) for r in rows]


# ── Overview and tech profile ────────────────────────────────────────────────

def test_overview_is_empty_until_a_version_is_approved(client, project_id):
    _seed(project_id, approved=False)
    body = _overview(client, project_id)
    assert body["document"] is None and body["epics"] == []
    assert len(body["unspecified_areas"]) == 9  # nothing entered yet


def test_overview_lists_epics_in_dependency_order(client, project_id):
    _seed(project_id)
    body = _overview(client, project_id)
    assert [e["external_id"] for e in body["epics"]] == ["E1", "E2"]
    assert [s["external_id"] for s in body["epics"][0]["stories"]] == ["S1", "S2"]


def test_tech_profile_is_saved_per_area(client, project_id):
    r = client.put(
        f"/projects/{project_id}/dev-stories/tech-profile",
        json={"areas": {"frontend": "React 19", "backend": "  .NET 9  ", "unknown": "ignored"}},
    )
    assert r.status_code == 200
    assert r.json()["areas"]["backend"] == ".NET 9"
    assert "unknown" not in r.json()["areas"]
    assert "frontend" not in _overview(client, project_id)["unspecified_areas"]
    assert "database" in _overview(client, project_id)["unspecified_areas"]


def test_uploaded_tech_document_fills_empty_areas_only(client, project_id):
    client.put(f"/projects/{project_id}/dev-stories/tech-profile", json={"areas": {"frontend": "Angular 18"}})

    r = client.post(
        f"/projects/{project_id}/dev-stories/tech-profile/document",
        files={"file": ("stack.md", b"# Stack\nBackend: Python 3.12 + FastAPI\nHosting: AWS ECS Fargate", "text/markdown")},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["areas"]["frontend"] == "Angular 18"  # typed value kept
    assert body["areas"]["backend"] == "Python 3.12 + FastAPI"  # filled from the document
    assert body["read_from_document"]["frontend"] == "Next.js 15 with TypeScript"
    assert body["document_name"] == "stack.md" and body["document_chars"] > 0
    # not saved until the person saves
    assert client.get(f"/projects/{project_id}/dev-stories/tech-profile").json()["areas"]["backend"] == ""
    assert len(_calls(project_id, "tech_profile")) == 1


def test_tech_document_must_be_a_readable_type(client, project_id):
    r = client.post(
        f"/projects/{project_id}/dev-stories/tech-profile/document",
        files={"file": ("stack.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 422


# ── Planning development stories ────────────────────────────────────────────

def test_generating_an_epic_plans_dev_stories_and_tasks(client, project_id, openai_fake):
    _seed(project_id)

    r = client.post(f"/projects/{project_id}/dev-stories/epics/E1/generate")

    assert r.status_code == 200, r.text
    stories = r.json()
    assert [s["source_story_external_id"] for s in stories] == ["S1", "S2"]  # S99 dropped
    first = stories[0]
    assert first["story_points"] == 5 and first["labels"] == ["registration", "frontend"]
    assert first["description"].startswith("Let a startup register") and "**Scope**\n- Registration form" in first["description"]
    assert [t["area"] for t in first["tasks"]] == ["backend", "frontend"]
    assert all(t["coding_prompt"] is None for t in first["tasks"])
    sent = openai_fake.client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "S1: Register" in sent and "S3" not in sent  # only this epic's stories
    assert len(_calls(project_id, "dev_story")) == 1


def test_regenerating_an_epic_replaces_its_plan(client, project_id):
    _seed(project_id)
    client.post(f"/projects/{project_id}/dev-stories/epics/E1/generate")
    client.post(f"/projects/{project_id}/dev-stories/epics/E1/generate")
    assert len(_overview(client, project_id)["epics"][0]["dev_stories"]) == 2


def test_an_epic_already_in_jira_is_not_replanned(client, project_id):
    _seed(project_id)
    story_id = client.post(f"/projects/{project_id}/dev-stories/epics/E1/generate").json()[0]["id"]
    with get_session() as s:
        s.get(DevStory, story_id).jira_key = "TK-301"

    r = client.post(f"/projects/{project_id}/dev-stories/epics/E1/generate")

    assert r.status_code == 409
    assert "already in Jira" in r.json()["detail"]


def test_generating_needs_an_approved_version_and_a_known_epic(client, project_id):
    _seed(project_id, approved=False)
    assert client.post(f"/projects/{project_id}/dev-stories/epics/E1/generate").status_code == 409
    _seed(project_id, version=2)
    assert client.post(f"/projects/{project_id}/dev-stories/epics/E9/generate").status_code == 404


# ── Coding prompts ───────────────────────────────────────────────────────────

def _plan_and_first_task(client, project_id):
    stories = client.post(f"/projects/{project_id}/dev-stories/epics/E1/generate").json()
    return stories, stories[0]["tasks"][0]


def test_coding_prompt_is_written_with_the_full_context(client, project_id, claude_fake):
    _seed(project_id)
    client.put(f"/projects/{project_id}/dev-stories/tech-profile", json={"areas": {"backend": "Python 3.12 + FastAPI"}})
    with get_session() as s:
        s.add(StandingPolicy(title="Audit logging", policy_text="Every change is logged with user and time."))
    stories, task = _plan_and_first_task(client, project_id)

    r = client.post(f"/projects/{project_id}/dev-stories/tasks/{task['id']}/coding-prompt")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["coding_prompt"].startswith("## Objective")
    assert body["tech_decision_needed"] is True and body["decision_areas"] == ["database"]
    sent = claude_fake.requests[-1]
    assert sent["output_config"] == {"effort": "high"}  # Bedrock has no structured outputs: plain Markdown back
    assert sent["thinking"] == {"type": "adaptive"}  # Opus 4.8 doesn't think unless asked
    text = sent["messages"][0]["content"]
    assert "- Backend [backend]: Python 3.12 + FastAPI" in text
    assert "- Database and storage [database]: not specified" in text
    assert "Audit logging: Every change is logged" in text
    assert "S1: Register" in text and "THIS TASK (backend): Build registration API" in text
    assert "(frontend) Build registration form" in text  # sibling task
    calls = _calls(project_id, "coding_prompt")
    assert len(calls) == 1
    assert calls[0][0] == CODING_PROMPT_MODEL
    assert calls[0][3] == pytest.approx(
        (6000 * CODING_PROMPT_INPUT_COST_PER_MILLION + 3000 * CODING_PROMPT_OUTPUT_COST_PER_MILLION) / 1_000_000
    )


def test_coding_prompt_carries_the_story_dependencies(client, project_id, claude_fake):
    _seed(project_id)
    stories, _ = _plan_and_first_task(client, project_id)
    s2_task = stories[1]["tasks"][0]

    client.post(f"/projects/{project_id}/dev-stories/tasks/{s2_task['id']}/coding-prompt")

    assert "S2 needs S1 Register (edits the profile S1 creates)" in claude_fake.requests[-1]["messages"][0]["content"]


def test_a_refused_prompt_keeps_the_previous_one(client, project_id, claude_fake):
    _seed(project_id)
    _, task = _plan_and_first_task(client, project_id)
    client.post(f"/projects/{project_id}/dev-stories/tasks/{task['id']}/coding-prompt")
    claude_fake.stop_reason = "refusal"

    r = client.post(f"/projects/{project_id}/dev-stories/tasks/{task['id']}/coding-prompt")

    assert r.status_code == 502 and "declined" in r.json()["detail"]
    task_after = _overview(client, project_id)["epics"][0]["dev_stories"][0]["tasks"][0]
    assert task_after["coding_prompt"].startswith("## Objective")


def test_editing_a_prompt_is_kept_apart_and_regenerating_resets_it(client, project_id):
    _seed(project_id)
    _, task = _plan_and_first_task(client, project_id)
    url = f"/projects/{project_id}/dev-stories/tasks/{task['id']}"
    client.post(f"{url}/coding-prompt")

    edited = client.patch(url, json={"edited_prompt": "## Objective\nMy version"}).json()
    assert edited["edited_prompt"] == "## Objective\nMy version"
    assert edited["coding_prompt"].startswith("## Objective\nBuild")
    assert client.patch(url, json={"edited_prompt": None}).json()["edited_prompt"] is None

    client.patch(url, json={"edited_prompt": "mine"})
    assert client.post(f"{url}/coding-prompt").json()["edited_prompt"] is None


# ── Editing ──────────────────────────────────────────────────────────────────

def test_stories_and_tasks_can_be_edited_and_deleted(client, project_id):
    _seed(project_id)
    stories, task = _plan_and_first_task(client, project_id)
    base = f"/projects/{project_id}/dev-stories"

    r = client.patch(f"{base}/stories/{stories[0]['id']}", json={"story_points": 8, "labels": ["auth"]})
    assert r.status_code == 200 and r.json()["story_points"] == 8 and r.json()["labels"] == ["auth"]
    assert client.patch(f"{base}/tasks/{task['id']}", json={"area": "data"}).json()["area"] == "data"
    assert client.patch(f"{base}/tasks/{task['id']}", json={"area": "design"}).status_code == 422

    assert client.delete(f"{base}/tasks/{task['id']}").status_code == 204
    assert client.delete(f"{base}/stories/{stories[1]['id']}").status_code == 204
    remaining = _overview(client, project_id)["epics"][0]["dev_stories"]
    assert len(remaining) == 1 and len(remaining[0]["tasks"]) == 1
    assert client.delete(f"{base}/stories/nope").status_code == 404


def test_missing_aws_credentials_are_reported_not_crashed(client, project_id, claude_fake):
    from botocore.exceptions import NoCredentialsError

    _seed(project_id)
    _, task = _plan_and_first_task(client, project_id)

    def no_credentials(**kwargs):
        raise NoCredentialsError()

    claude_fake.messages = SimpleNamespace(stream=no_credentials)
    r = client.post(f"/projects/{project_id}/dev-stories/tasks/{task['id']}/coding-prompt")

    assert r.status_code == 502
    assert "AWS credentials failed" in r.json()["detail"]


def test_decisions_are_read_from_the_technology_section_only():
    from ai.text.coding_prompt_generator import technology_decisions

    assert technology_decisions("## Objective\nx\n\n## Technology\n- Backend [backend]: FastAPI\n") == []
    assert technology_decisions("## Technology\n- Frontend [frontend]: **Decision needed**\n## Tests\n") == ["frontend"]
    # a decision whose area isn't named still flags the prompt
    assert technology_decisions("## Technology\n- Hosting: Decision needed\n") == [""]
    assert technology_decisions("no sections at all, Decision needed [frontend]") == []


def test_a_fenced_or_empty_answer_is_handled(client, project_id, claude_fake):
    _seed(project_id)
    _, task = _plan_and_first_task(client, project_id)

    claude_fake.answer = "```markdown\n## Objective\nDo it.\n\n## Technology\n- Backend [backend]: FastAPI\n```"
    body = client.post(f"/projects/{project_id}/dev-stories/tasks/{task['id']}/coding-prompt").json()
    assert body["coding_prompt"] == "## Objective\nDo it.\n\n## Technology\n- Backend [backend]: FastAPI"
    assert body["tech_decision_needed"] is False and body["decision_areas"] == []

    claude_fake.answer = "   "
    r = client.post(f"/projects/{project_id}/dev-stories/tasks/{task['id']}/coding-prompt")
    assert r.status_code == 502 and "no prompt text" in r.json()["detail"]


# ── Claude through a role in another AWS account ─────────────────────────────

class _FakeSts:
    def __init__(self, expires_in: timedelta, fail: bool = False):
        self.calls: list[dict] = []
        self.expires_in = expires_in
        self.fail = fail

    def assume_role(self, **kwargs):
        from botocore.exceptions import ClientError

        self.calls.append(kwargs)
        if self.fail:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "not authorized"}}, "AssumeRole")
        return {
            "Credentials": {
                "AccessKeyId": f"key-{len(self.calls)}",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
                "Expiration": datetime.now(timezone.utc) + self.expires_in,
            }
        }


@pytest.fixture
def role_setup(monkeypatch):
    """coding_prompt_role_arn set, STS and the Bedrock client faked; returns (sts, clients built)."""
    import anthropic
    import boto3
    import config
    from app import deps

    built: list[dict] = []
    sts = _FakeSts(timedelta(hours=1))
    monkeypatch.setattr(config, "CODING_PROMPT_ROLE_ARN", "arn:aws:iam::111111111111:role/adlc-coding-prompts")
    monkeypatch.setattr(boto3, "client", lambda service, region_name=None: sts)
    monkeypatch.setattr(anthropic, "AnthropicBedrock", lambda **kwargs: built.append(kwargs) or kwargs)
    monkeypatch.setattr(deps, "_role_credentials", None)
    return sts, built


def test_the_coding_client_uses_the_other_accounts_role_and_reuses_it(role_setup):
    from app.deps import get_coding_llm_client

    sts, built = role_setup
    get_coding_llm_client()
    get_coding_llm_client()

    assert len(sts.calls) == 1  # credentials reused while they're fresh
    assert sts.calls[0]["RoleArn"] == "arn:aws:iam::111111111111:role/adlc-coding-prompts"
    assert built[0]["aws_access_key"] == "key-1" and built[0]["aws_session_token"] == "token"
    assert built[0]["aws_region"] == "eu-central-1"


def test_role_credentials_are_renewed_before_they_expire(role_setup):
    from app.deps import get_coding_llm_client

    sts, built = role_setup
    sts.expires_in = timedelta(minutes=3)  # inside the five-minute margin
    get_coding_llm_client()
    get_coding_llm_client()

    assert len(sts.calls) == 2 and built[1]["aws_access_key"] == "key-2"


def test_a_role_that_cant_be_assumed_is_reported_not_crashed(client, project_id, role_setup):
    from app.deps import get_coding_llm_client

    sts, _ = role_setup
    sts.fail = True
    app.dependency_overrides.pop(get_coding_llm_client, None)  # the real getter, not claude_fake
    _seed(project_id)
    _, task = _plan_and_first_task(client, project_id)

    r = client.post(f"/projects/{project_id}/dev-stories/tasks/{task['id']}/coding-prompt")

    assert r.status_code == 502
    assert "role in the other AWS account" in r.json()["detail"]
