"""
HTTP-level tests for the UI/UX Prompts feature (Figma Make prompts generated
from an approved requirements version's epics/stories). OpenAI is mocked:
get_openai_client returns a fake whose chat.completions.create answers a
tool-call request (the prompt itself) or a plain-content request (the
optional screenshot description), so the real generator, service and router
all run — only the model is fake.
"""
import io
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db.models import AiCall, Document, Project, RequirementItem, UxPrompt
from app.db.session import get_session
from app.deps import get_openai_client
from app.main import app
from app.services import requirements_review as review

PROMPT_TEXT = "PRODUCT CONTEXT\n- Strategy tool\nSCREENS\n- Screen: Hierarchy List (S1, S2)\nDO NOT\n- add extras"
TOKENS = "Primary #0A66FF; Inter 14/16/20; 8pt spacing; radius 8; sidebar shell"


def _tool_response(prompt_text=PROMPT_TEXT, tokens=TOKENS):
    args = json.dumps(
        {"prompt_text": prompt_text, "screen_names": ["Hierarchy List"], "design_tokens_summary": tokens}
    )
    call = SimpleNamespace(function=SimpleNamespace(name="record_ux_prompt", arguments=args))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=""))],
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500),
    )


def _vision_response(text="Table screen with a filter bar and a 'New item' button."):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content=text))],
        usage=SimpleNamespace(prompt_tokens=800, completion_tokens=120),
    )


class FakeLLM:
    def __init__(self):
        self.client = MagicMock()
        self.client.chat.completions.create.side_effect = self._create

    def _create(self, **kwargs):
        return _tool_response() if kwargs.get("tools") else _vision_response()

    def user_messages(self):
        """The user-message text of every prompt-generation call made so far."""
        out = []
        for call in self.client.chat.completions.create.call_args_list:
            if call.kwargs.get("tools"):
                out.append(call.kwargs["messages"][1]["content"])
        return out

    @property
    def call_count(self):
        return self.client.chat.completions.create.call_count


@pytest.fixture
def llm():
    fake = FakeLLM()
    app.dependency_overrides[get_openai_client] = lambda: fake.client
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(llm):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project_id(client):
    r = client.post("/projects", json={"name": f"pytest-ux-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed(project_id, approved=True, from_change_request=False):
    """One requirements version: epic E1 with stories S1, S2; epic E2 with S3."""
    with get_session() as s:
        doc = Document(
            project_id=project_id,
            doc_type="requirement",
            version=1,
            approval_status="approved" if approved else "draft",
            source_filename="sow.pdf",
            type_metadata={"source_change_request_id": "cr-1"} if from_change_request else None,
        )
        s.add(doc)
        s.flush()
        e1 = RequirementItem(document_id=doc.id, type="epic", external_id="E1", text="Strategy hierarchy")
        e2 = RequirementItem(document_id=doc.id, type="epic", external_id="E2", text="Reporting")
        s.add_all([e1, e2])
        s.flush()

        def story(ext, epic, title):
            return RequirementItem(
                document_id=doc.id,
                type="story",
                external_id=ext,
                parent_id=epic.id,
                text=title,
                description=f"As an Admin, I want {title.lower()}, so that I can work faster.",
                acceptance_criteria=[{"text": "Item appears in the list", "out_of_scope": False}],
                scenarios=[{"title": "Create", "given": "I am on the list", "when": "I click New", "then": "a form opens"}],
                error_handling=[{"condition": "Name missing", "message": "Enter a name."}],
            )

        s1, s2, s3 = story("S1", e1, "Create hierarchy"), story("S2", e1, "Edit hierarchy"), story("S3", e2, "View report")
        s.add_all([s1, s2, s3])
        s.flush()
        return {"doc": doc.id, "e1": e1.id, "e2": e2.id, "s1": s1.id, "s2": s2.id, "s3": s3.id}


def _generate(client, project_id, ids, mode="foundation", story_keys=("s1", "s2"), epic="e1", **extra):
    data = {
        "document_id": ids["doc"],
        "epic_id": ids[epic],
        "story_ids": json.dumps([ids[k] for k in story_keys]),
        "mode": mode,
        **extra,
    }
    return client.post(f"/projects/{project_id}/ux-prompts", data=data)


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format="PNG")
    return buf.getvalue()


def _ai_calls(project_id):
    with get_session() as s:
        rows = s.query(AiCall).filter(AiCall.project_id == project_id, AiCall.call_type == "ux_prompt").all()
        return [SimpleNamespace(input_tokens=r.input_tokens, output_tokens=r.output_tokens) for r in rows]


def test_sources_empty_until_a_version_is_approved(client, project_id):
    r = client.get(f"/projects/{project_id}/ux-prompts/sources")
    assert r.status_code == 200
    assert r.json()["document"] is None
    assert r.json()["epics"] == []

    _seed(project_id, approved=False)
    assert client.get(f"/projects/{project_id}/ux-prompts/sources").json()["document"] is None


def test_sources_lists_epics_with_stories_and_defaults_to_foundation(client, project_id):
    ids = _seed(project_id)
    body = client.get(f"/projects/{project_id}/ux-prompts/sources").json()
    assert body["document"]["id"] == ids["doc"]
    assert [e["epic"]["external_id"] for e in body["epics"]] == ["E1", "E2"]
    assert [s["external_id"] for s in body["epics"][0]["stories"]] == ["S1", "S2"]
    assert body["suggested_mode"] == "foundation"
    assert body["has_design_system"] is False


def test_change_request_version_suggests_edit_existing(client, project_id):
    _seed(project_id, from_change_request=True)
    assert client.get(f"/projects/{project_id}/ux-prompts/sources").json()["suggested_mode"] == "edit_existing"


def test_generation_requires_an_approved_version(client, project_id, llm):
    ids = _seed(project_id, approved=False)
    r = _generate(client, project_id, ids)
    assert r.status_code == 422
    assert "approved" in r.json()["detail"]
    assert llm.call_count == 0


def test_foundation_generation_saves_prompt_logs_cost_and_remembers_design_system(client, project_id, llm):
    ids = _seed(project_id)
    brief = {"reference_brand": "Apple HIG", "primary_color": "#0A66FF", "appearance": "both", "platform": "web"}
    r = _generate(client, project_id, ids, style_brief=json.dumps(brief))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mode"] == "foundation"
    assert body["prompt_text"] == PROMPT_TEXT
    assert body["epic_external_id"] == "E1"
    assert body["story_external_ids"] == ["S1", "S2"]
    assert body["is_stale"] is False
    assert body["char_count"] == len(PROMPT_TEXT)
    assert body["style_brief"]["reference_brand"] == "Apple HIG"

    # the model saw the stories' scenarios and error wording, and the brief
    sent = llm.user_messages()[0]
    assert "Create hierarchy" in sent and "Enter a name." in sent and "Apple HIG" in sent
    assert "View report" not in sent  # story from another epic was not selected

    calls = _ai_calls(project_id)
    assert len(calls) == 1 and calls[0].input_tokens == 1000

    # the design system is remembered, and the brief is saved on the project
    sources = client.get(f"/projects/{project_id}/ux-prompts/sources").json()
    assert sources["has_design_system"] is True
    assert sources["suggested_mode"] == "new_feature"
    assert sources["style_brief"]["primary_color"] == "#0A66FF"
    assert sources["style_brief"]["design_tokens_summary"] == TOKENS


def test_new_feature_prompt_receives_saved_design_tokens_and_leaves_them_alone(client, project_id, llm):
    ids = _seed(project_id)
    assert _generate(client, project_id, ids).status_code == 201  # foundation saves tokens
    with get_session() as s:
        s.query(Project).filter(Project.id == project_id).one().style_brief = {"design_tokens_summary": "SAVED TOKENS"}

    r = _generate(client, project_id, ids, mode="new_feature", epic="e2", story_keys=("s3",))
    assert r.status_code == 201, r.text
    assert "SAVED TOKENS" in llm.user_messages()[-1]
    # a non-foundation generation must not overwrite the saved design system
    assert client.get(f"/projects/{project_id}/ux-prompts/sources").json()["style_brief"]["design_tokens_summary"] == "SAVED TOKENS"


def test_stories_must_belong_to_the_epic(client, project_id, llm):
    ids = _seed(project_id)
    r = _generate(client, project_id, ids, story_keys=("s1", "s3"))  # s3 is under E2
    assert r.status_code == 422
    assert "does not belong" in r.json()["detail"]
    assert llm.call_count == 0

    assert _generate(client, project_id, ids, story_keys=()).status_code == 422


def test_unknown_document_is_404(client, project_id):
    ids = _seed(project_id)
    ids["doc"] = "nope"
    assert _generate(client, project_id, ids).status_code == 404


def test_edit_existing_with_screenshot_describes_it_first(client, project_id, llm):
    ids = _seed(project_id)
    r = client.post(
        f"/projects/{project_id}/ux-prompts",
        data={
            "document_id": ids["doc"],
            "epic_id": ids["e1"],
            "story_ids": json.dumps([ids["s1"]]),
            "mode": "edit_existing",
        },
        files={"screenshot": ("current.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 201, r.text
    assert llm.call_count == 2  # one vision call, one generation call
    assert "filter bar" in llm.user_messages()[0]
    assert r.json()["style_brief"]["existing_screen_description"].startswith("Table screen")
    assert len(_ai_calls(project_id)) == 2


def test_screenshot_only_allowed_in_edit_mode(client, project_id, llm):
    ids = _seed(project_id)
    r = client.post(
        f"/projects/{project_id}/ux-prompts",
        data={"document_id": ids["doc"], "epic_id": ids["e1"], "story_ids": json.dumps([ids["s1"]]), "mode": "foundation"},
        files={"screenshot": ("current.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 422
    assert llm.call_count == 0


def test_screenshot_must_be_a_supported_image(client, project_id, llm):
    ids = _seed(project_id)
    r = client.post(
        f"/projects/{project_id}/ux-prompts",
        data={"document_id": ids["doc"], "epic_id": ids["e1"], "story_ids": json.dumps([ids["s1"]]), "mode": "edit_existing"},
        files={"screenshot": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400
    assert llm.call_count == 0


def test_edit_reset_and_regenerate(client, project_id, llm):
    ids = _seed(project_id)
    pid = _generate(client, project_id, ids).json()["id"]

    r = client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": "my tweaked prompt"})
    assert r.json()["edited_text"] == "my tweaked prompt"
    assert r.json()["prompt_text"] == PROMPT_TEXT  # original is preserved
    assert r.json()["char_count"] == len("my tweaked prompt")

    # an edit identical to the generated text is stored as no edit
    r = client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": PROMPT_TEXT})
    assert r.json()["edited_text"] is None

    client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": "again"})
    assert client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": None}).json()["edited_text"] is None

    client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": "before regenerate"})
    r = client.post(f"/projects/{project_id}/ux-prompts/{pid}/regenerate")
    assert r.status_code == 200, r.text
    assert r.json()["edited_text"] is None
    assert llm.call_count == 2
    assert len(_ai_calls(project_id)) == 2


def test_list_and_delete(client, project_id):
    ids = _seed(project_id)
    pid = _generate(client, project_id, ids).json()["id"]
    assert [p["id"] for p in client.get(f"/projects/{project_id}/ux-prompts").json()] == [pid]

    assert client.delete(f"/projects/{project_id}/ux-prompts/{pid}").status_code == 204
    assert client.get(f"/projects/{project_id}/ux-prompts").json() == []
    assert client.delete(f"/projects/{project_id}/ux-prompts/{pid}").status_code == 404


def test_prompt_of_another_project_is_not_reachable(client, project_id):
    ids = _seed(project_id)
    pid = _generate(client, project_id, ids).json()["id"]
    other = client.post("/projects", json={"name": f"pytest-ux-other-{uuid.uuid4().hex[:8]}"}).json()["id"]
    assert client.patch(f"/projects/{other}/ux-prompts/{pid}", json={"edited_text": "x"}).status_code == 404


def test_prompts_go_stale_when_the_version_is_superseded(client, project_id):
    ids = _seed(project_id)
    pid = _generate(client, project_id, ids).json()["id"]

    with get_session() as s:
        review.fork_new_version(s, s.query(Document).filter(Document.id == ids["doc"]).one())

    prompts = client.get(f"/projects/{project_id}/ux-prompts").json()
    assert prompts[0]["id"] == pid and prompts[0]["is_stale"] is True
    with get_session() as s:
        assert s.query(UxPrompt).filter(UxPrompt.id == pid).one().is_stale is True


def test_style_brief_save_does_not_wipe_design_tokens(client, project_id):
    ids = _seed(project_id)
    _generate(client, project_id, ids)  # saves TOKENS

    r = client.put(f"/projects/{project_id}/ux-prompts/style-brief", json={"tone": "calm, precise"})
    assert r.status_code == 200
    saved = client.get(f"/projects/{project_id}/ux-prompts/sources").json()["style_brief"]
    assert saved["tone"] == "calm, precise"
    assert saved["design_tokens_summary"] == TOKENS

    # ...but the PM can replace it explicitly
    client.put(f"/projects/{project_id}/ux-prompts/style-brief", json={"design_tokens_summary": "PASTED"})
    assert client.get(f"/projects/{project_id}/ux-prompts/sources").json()["style_brief"]["design_tokens_summary"] == "PASTED"
