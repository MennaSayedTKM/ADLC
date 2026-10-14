"""
HTTP-level tests for the UI/UX Prompts feature: a Platform Blueprint prompt
for the whole platform, then one feature/edit prompt per epic that snaps into
the blueprint's navigation slots, kept consistent through a context pack.
OpenAI is mocked: get_openai_client returns a fake that answers by tool name
(the prompt, the feature-relationship map, the vision draft) or, with no
tools, a screenshot description — so the real generator, service and router
all run, only the model is fake.
"""
import io
import json
import re
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
from app.deps import get_openai_client, get_optional_openai_client
from app.main import app
from app.services import requirements_review as review
from app.services import style_reference
from app.services.ux_prompts import order_epics

TOKENS = "Primary #0A66FF; Inter 14/16/20; 8pt spacing; radius 8; sidebar shell"


def _response(payload=None, tool_name=None, content=""):
    if tool_name:
        call = SimpleNamespace(function=SimpleNamespace(name=tool_name, arguments=json.dumps(payload)))
        message = SimpleNamespace(tool_calls=[call], content="")
    else:
        message = SimpleNamespace(tool_calls=None, content=content)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500),
    )


class FakeLLM:
    """Answers each kind of call the feature makes. `relations` is the feature map the model 'finds'."""

    def __init__(self, relations=None):
        self.relations = relations or []
        self.story_relations = []
        self.client = MagicMock()
        self.client.chat.completions.create.side_effect = self._create

    def _create(self, **kwargs):
        tools = kwargs.get("tools")
        if not tools:
            return _response(content="Table screen with a filter bar and a 'New item' button.")
        name = tools[0]["function"]["name"]
        if name == "record_feature_relationships":
            return _response({"features": self.relations, "story_dependencies": self.story_relations}, name)
        if name == "record_vision":
            return _response({"vision": "A calm strategy tool.", "target_users": "Strategy Office"}, name)

        user = kwargs["messages"][1]["content"]
        if "PLANNED FEATURES" in user:  # platform blueprint
            planned = re.findall(r"^(E\d+): (.+)$", user, re.M)
            return _response(
                {
                    "prompt_text": "BLUEPRINT\n- vision\nPLACEHOLDERS\n" + "\n".join(f"- {e} {t}" for e, t in planned),
                    "screens": [{"name": "Home", "route": "/home", "purpose": "Landing dashboard"}],
                    "design_tokens_summary": TOKENS,
                    "nav_items": [
                        {"epic_external_id": e, "label": t, "route": f"/{e.lower()}-slot"} for e, t in planned
                    ],
                    "component_names": ["Button", "DataTable"],
                },
                name,
            )
        epic = re.search(r"^EPIC (E\d+):", user, re.M).group(1)
        return _response(
            {
                "prompt_text": f"FEATURE {epic}\nSCREENS\n- Screen: {epic} List",
                "screens": [{"name": f"{epic} List", "route": f"/{epic.lower()}/list", "purpose": f"List for {epic}"}],
                "design_tokens_summary": "",
                "nav_items": [],
                "component_names": [],
            },
            name,
        )

    def prompt_requests(self):
        """User-message text of every record_ux_prompt call so far, in order."""
        return [
            c.kwargs["messages"][1]["content"]
            for c in self.client.chat.completions.create.call_args_list
            if c.kwargs.get("tools") and c.kwargs["tools"][0]["function"]["name"] == "record_ux_prompt"
        ]

    @property
    def call_count(self):
        return self.client.chat.completions.create.call_count


@pytest.fixture
def llm():
    fake = FakeLLM()
    app.dependency_overrides[get_openai_client] = lambda: fake.client
    app.dependency_overrides[get_optional_openai_client] = lambda: fake.client
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


def _seed(project_id, approved=True, from_change_request=False, version=1, extra_epic=False):
    """One requirements version: E1 (S1, S2), E2 (S3) and optionally E3 (S4)."""
    with get_session() as s:
        doc = Document(
            project_id=project_id,
            doc_type="requirement",
            version=version,
            approval_status="approved" if approved else "draft",
            source_filename="sow.pdf",
            type_metadata={"source_change_request_id": "cr-1"} if from_change_request else None,
        )
        s.add(doc)
        s.flush()
        epics = {"e1": "Strategy hierarchy", "e2": "Reporting"}
        if extra_epic:
            epics["e3"] = "Notifications"
        rows = {}
        for key, title in epics.items():
            rows[key] = RequirementItem(document_id=doc.id, type="epic", external_id=key.upper(), text=title)
        s.add_all(rows.values())
        s.flush()

        def story(ext, epic, title):
            return RequirementItem(
                document_id=doc.id,
                type="story",
                external_id=ext,
                parent_id=rows[epic].id,
                text=title,
                description=f"As an Admin, I want {title.lower()}, so that I can work faster.",
                acceptance_criteria=[{"text": "Item appears in the list", "out_of_scope": False}],
                scenarios=[{"title": "Create", "given": "I am on the list", "when": "I click New", "then": "a form opens"}],
                error_handling=[{"condition": "Name missing", "message": "Enter a name."}],
            )

        stories = {
            "s1": story("S1", "e1", "Create hierarchy"),
            "s2": story("S2", "e1", "Edit hierarchy"),
            "s3": story("S3", "e2", "View report"),
        }
        if extra_epic:
            stories["s4"] = story("S4", "e3", "Send alert")
        s.add_all(stories.values())
        s.flush()
        return {"doc": doc.id, **{k: v.id for k, v in rows.items()}, **{k: v.id for k, v in stories.items()}}


def _blueprint(client, project_id, ids, **extra):
    data = {"document_id": ids["doc"], "mode": "foundation", **extra}
    return client.post(f"/projects/{project_id}/ux-prompts", data=data)


def _feature(client, project_id, ids, epic="e1", story_keys=("s1", "s2"), mode="new_feature", **extra):
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
        return [SimpleNamespace(input_tokens=r.input_tokens) for r in rows]


def _sources(client, project_id):
    return client.get(f"/projects/{project_id}/ux-prompts/sources").json()


# ── Sources and gating ───────────────────────────────────────────────────────

def test_sources_empty_until_a_version_is_approved(client, project_id):
    body = _sources(client, project_id)
    assert body["document"] is None and body["epics"] == []

    _seed(project_id, approved=False)
    assert _sources(client, project_id)["document"] is None


def test_sources_default_to_blueprint_first(client, project_id):
    ids = _seed(project_id)
    body = _sources(client, project_id)
    assert body["document"]["id"] == ids["doc"]
    assert [e["epic"]["external_id"] for e in body["epics"]] == ["E1", "E2"]
    assert body["suggested_mode"] == "foundation"
    assert body["has_blueprint"] is False


def test_generation_requires_an_approved_version(client, project_id, llm):
    ids = _seed(project_id, approved=False)
    r = _blueprint(client, project_id, ids)
    assert r.status_code == 422 and "approved" in r.json()["detail"]
    assert llm.call_count == 0


def test_unknown_document_is_404(client, project_id):
    ids = _seed(project_id)
    ids["doc"] = "nope"
    assert _blueprint(client, project_id, ids).status_code == 404


# ── Platform blueprint ───────────────────────────────────────────────────────

def test_blueprint_is_not_tied_to_an_epic_and_gives_every_epic_a_slot(client, project_id, llm):
    ids = _seed(project_id)
    brief = {"vision": "A calm platform for the Strategy Office", "reference_brand": "Apple", "platform": "web"}
    r = _blueprint(client, project_id, ids, style_brief=json.dumps(brief))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mode"] == "foundation"
    assert body["epic_item_id"] is None and body["epic_external_id"] is None and body["story_ids"] == []
    assert body["screens"] == [{"name": "Home", "route": "/home", "purpose": "Landing dashboard"}]

    # the model was asked about the whole platform: vision + every planned epic, not one epic
    sent = llm.prompt_requests()[0]
    assert "A calm platform for the Strategy Office" in sent
    assert "E1: Strategy hierarchy" in sent and "E2: Reporting" in sent

    sources = _sources(client, project_id)
    assert sources["has_blueprint"] is True and sources["blueprint_prompt_id"] == body["id"]
    assert [(s["epic_external_id"], s["status"]) for s in sources["sitemap"]] == [("E1", "placeholder"), ("E2", "placeholder")]
    assert sources["style_brief"]["design_tokens_summary"] == TOKENS
    assert sources["style_brief"]["component_names"] == ["Button", "DataTable"]
    assert sources["suggested_mode"] == "new_feature"
    assert sources["registry"][0]["owner"] == "Platform"

    # relationships call + prompt call, both logged
    assert llm.call_count == 2 and len(_ai_calls(project_id)) == 2


def test_blueprint_without_a_vision_still_generates(client, project_id, llm):
    ids = _seed(project_id)
    assert _blueprint(client, project_id, ids).status_code == 201
    assert "not provided" in llm.prompt_requests()[0]


def test_blueprint_includes_extracted_reference_styles(client, project_id, llm):
    ids = _seed(project_id)
    ref = {
        "url": "https://example.com",
        "title": "Example",
        "note": "overall feel",
        "style_tags": {
            "palette": [{"hex": "#0071E3", "count": 12, "kind": "accent"}],
            "accent_guess": "#0071E3",
            "fonts": ["SF Pro Display"],
            "radii": ["12px"],
        },
    }
    assert _blueprint(client, project_id, ids, style_brief=json.dumps({"reference_styles": [ref]})).status_code == 201
    sent = llm.prompt_requests()[0]
    assert "REFERENCE STYLES" in sent and "#0071E3" in sent and "SF Pro Display" in sent and "overall feel" in sent


def test_only_one_blueprint_per_project(client, project_id, llm):
    ids = _seed(project_id)
    assert _blueprint(client, project_id, ids).status_code == 201
    r = _blueprint(client, project_id, ids)
    assert r.status_code == 409 and "regenerate" in r.json()["detail"]


def test_regenerating_the_blueprint_picks_up_epics_approved_later(client, project_id, llm):
    ids = _seed(project_id)
    pid = _blueprint(client, project_id, ids).json()["id"]

    ids2 = _seed(project_id, version=2, extra_epic=True)  # a newer approved version with a new epic E3
    sources = _sources(client, project_id)
    assert sources["document"]["id"] == ids2["doc"]
    assert sources["epics_missing_from_blueprint"] == ["E3"]

    r = client.post(f"/projects/{project_id}/ux-prompts/{pid}/regenerate")
    assert r.status_code == 200, r.text
    assert r.json()["document_id"] == ids2["doc"]
    sources = _sources(client, project_id)
    assert sources["epics_missing_from_blueprint"] == []
    assert [s["epic_external_id"] for s in sources["sitemap"]] == ["E1", "E2", "E3"]


def test_blueprint_survives_a_style_brief_save(client, project_id):
    ids = _seed(project_id)
    _blueprint(client, project_id, ids)

    r = client.put(f"/projects/{project_id}/ux-prompts/style-brief", json={"tone": "calm, precise"})
    assert r.status_code == 200
    saved = _sources(client, project_id)["style_brief"]
    assert saved["tone"] == "calm, precise"
    assert saved["design_tokens_summary"] == TOKENS and len(saved["sitemap"]) == 2  # untouched

    client.put(f"/projects/{project_id}/ux-prompts/style-brief", json={"design_tokens_summary": "PASTED", "tone": ""})
    saved = _sources(client, project_id)["style_brief"]
    assert saved["design_tokens_summary"] == "PASTED" and "tone" not in saved


def test_draft_vision_needs_an_approved_version_and_is_not_saved(client, project_id, llm):
    assert client.post(f"/projects/{project_id}/ux-prompts/vision/draft").status_code == 422
    _seed(project_id)
    r = client.post(f"/projects/{project_id}/ux-prompts/vision/draft")
    assert r.status_code == 200 and r.json() == {"vision": "A calm strategy tool.", "target_users": "Strategy Office"}
    assert "vision" not in _sources(client, project_id)["style_brief"]
    assert len(_ai_calls(project_id)) == 1


# ── Feature prompts and consistency ──────────────────────────────────────────

def test_feature_needs_the_blueprint_first(client, project_id, llm):
    ids = _seed(project_id)
    r = _feature(client, project_id, ids)
    assert r.status_code == 422 and "blueprint" in r.json()["detail"]
    assert llm.call_count == 0

    # ...unless the PM supplies an existing design system summary
    client.put(f"/projects/{project_id}/ux-prompts/style-brief", json={"design_tokens_summary": "PASTED SYSTEM"})
    assert _feature(client, project_id, ids).status_code == 201
    assert "PASTED SYSTEM" in llm.prompt_requests()[-1]


def test_feature_prompt_carries_the_platform_context(client, project_id, llm):
    ids = _seed(project_id)
    _blueprint(client, project_id, ids, style_brief=json.dumps({"vision": "A calm strategy platform"}))

    r = _feature(client, project_id, ids, epic="e1")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mode"] == "new_feature" and body["epic_external_id"] == "E1"
    assert body["story_external_ids"] == ["S1", "S2"]
    assert body["screens"][0]["route"] == "/e1/list"

    sent = llm.prompt_requests()[-1]
    assert "PLATFORM CONTEXT" in sent
    assert TOKENS in sent                                    # the design system to reuse
    assert "Components to reuse: Button, DataTable" in sent  # component inventory
    assert "Strategy hierarchy -> /e1-slot [placeholder]  <- THIS FEATURE" in sent  # its slot
    assert "Reporting -> /e2-slot [placeholder]" in sent     # the rest of the navigation
    assert "Home (/home)" in sent                            # screens already designed
    assert "Create hierarchy" in sent and "Enter a name." in sent
    assert "View report" not in sent                         # S3 belongs to another epic

    # the slot is now designed, and the new screens joined the registry
    sources = _sources(client, project_id)
    assert {s["epic_external_id"]: s["status"] for s in sources["sitemap"]} == {"E1": "designed", "E2": "placeholder"}
    assert "/e1/list" in [s["route"] for s in sources["registry"]]


def test_dependent_feature_sees_the_screens_it_depends_on(client, project_id, llm):
    llm.relations = [
        {"epic_external_id": "E1", "depends_on": [], "integrates": []},
        {
            "epic_external_id": "E2",
            "depends_on": ["E1", "E2", "E9"],  # self and unknown ids must be dropped
            "integrates": [{"with_epic": "E1", "how": "report rows link back to hierarchy items"}],
        },
    ]
    ids = _seed(project_id)
    _blueprint(client, project_id, ids)
    assert _sources(client, project_id)["feature_map"][1]["depends_on"] == ["E1"]

    _feature(client, project_id, ids, epic="e1")
    _feature(client, project_id, ids, epic="e2", story_keys=("s3",))
    sent = llm.prompt_requests()[-1]
    assert "Depends on" in sent and "E1 Strategy hierarchy: screens E1 List (/e1/list)" in sent
    assert "report rows link back to hierarchy items" in sent


def test_suggested_order_puts_dependencies_first(client, project_id, llm):
    llm.relations = [{"epic_external_id": "E1", "depends_on": ["E2"], "integrates": []}]
    ids = _seed(project_id)
    _blueprint(client, project_id, ids)
    assert _sources(client, project_id)["suggested_order"] == ["E2", "E1"]


def test_order_epics_ties_and_cycles():
    assert order_epics(["E3", "E1", "E2"], []) == ["E1", "E2", "E3"]
    fm = [
        {"epic_external_id": "E1", "depends_on": ["E2"]},
        {"epic_external_id": "E2", "depends_on": ["E1"]},  # cycle: must still terminate
        {"epic_external_id": "E3", "depends_on": []},
    ]
    assert sorted(order_epics(["E1", "E2", "E3"], fm)) == ["E1", "E2", "E3"]


def test_deleting_a_feature_prompt_removes_its_screens_from_the_registry(client, project_id):
    ids = _seed(project_id)
    _blueprint(client, project_id, ids)
    pid = _feature(client, project_id, ids).json()["id"]
    assert "/e1/list" in [s["route"] for s in _sources(client, project_id)["registry"]]

    assert client.delete(f"/projects/{project_id}/ux-prompts/{pid}").status_code == 204
    sources = _sources(client, project_id)
    assert "/e1/list" not in [s["route"] for s in sources["registry"]]
    assert sources["sitemap"][0]["status"] == "placeholder"


def test_stories_must_belong_to_the_epic(client, project_id, llm):
    ids = _seed(project_id)
    _blueprint(client, project_id, ids)
    calls = llm.call_count
    r = _feature(client, project_id, ids, story_keys=("s1", "s3"))  # s3 is under E2
    assert r.status_code == 422 and "does not belong" in r.json()["detail"]
    assert _feature(client, project_id, ids, story_keys=()).status_code == 422
    assert llm.call_count == calls


def test_feature_requires_an_epic(client, project_id):
    ids = _seed(project_id)
    r = client.post(
        f"/projects/{project_id}/ux-prompts", data={"document_id": ids["doc"], "mode": "new_feature"}
    )
    assert r.status_code == 422


# ── Edit existing and screenshots ────────────────────────────────────────────

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
    assert "filter bar" in llm.prompt_requests()[0]
    assert r.json()["style_brief"]["existing_screen_description"].startswith("Table screen")
    assert len(_ai_calls(project_id)) == 2


def test_screenshot_only_allowed_in_edit_mode(client, project_id, llm):
    ids = _seed(project_id)
    _blueprint(client, project_id, ids)
    calls = llm.call_count
    r = client.post(
        f"/projects/{project_id}/ux-prompts",
        data={"document_id": ids["doc"], "epic_id": ids["e1"], "story_ids": json.dumps([ids["s1"]]), "mode": "new_feature"},
        files={"screenshot": ("current.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 422 and llm.call_count == calls


def test_screenshot_must_be_a_supported_image(client, project_id, llm):
    ids = _seed(project_id)
    r = client.post(
        f"/projects/{project_id}/ux-prompts",
        data={"document_id": ids["doc"], "epic_id": ids["e1"], "story_ids": json.dumps([ids["s1"]]), "mode": "edit_existing"},
        files={"screenshot": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400 and llm.call_count == 0


def test_change_request_version_suggests_edit_once_a_blueprint_exists(client, project_id):
    ids = _seed(project_id, from_change_request=True)
    assert _sources(client, project_id)["suggested_mode"] == "foundation"
    _blueprint(client, project_id, ids)
    assert _sources(client, project_id)["suggested_mode"] == "edit_existing"


# ── Editing, regenerating, listing ───────────────────────────────────────────

def test_edit_reset_and_regenerate(client, project_id, llm):
    ids = _seed(project_id)
    _blueprint(client, project_id, ids)
    created = _feature(client, project_id, ids).json()
    pid, original = created["id"], created["prompt_text"]

    r = client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": "my tweaked prompt"})
    assert r.json()["edited_text"] == "my tweaked prompt" and r.json()["prompt_text"] == original
    assert r.json()["char_count"] == len("my tweaked prompt")

    r = client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": original})
    assert r.json()["edited_text"] is None  # identical to generated = no edit

    client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": "again"})
    assert client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": None}).json()["edited_text"] is None

    client.patch(f"/projects/{project_id}/ux-prompts/{pid}", json={"edited_text": "before regenerate"})
    r = client.post(f"/projects/{project_id}/ux-prompts/{pid}/regenerate")
    assert r.status_code == 200, r.text
    assert r.json()["edited_text"] is None and r.json()["screens"][0]["route"] == "/e1/list"


def test_regenerating_a_feature_does_not_count_its_own_old_screens_as_existing(client, project_id, llm):
    ids = _seed(project_id)
    _blueprint(client, project_id, ids)
    pid = _feature(client, project_id, ids).json()["id"]
    client.post(f"/projects/{project_id}/ux-prompts/{pid}/regenerate")
    assert "E1 List (/e1/list)" not in llm.prompt_requests()[-1]


def test_list_other_projects_and_staleness(client, project_id):
    ids = _seed(project_id)
    bid = _blueprint(client, project_id, ids).json()["id"]
    assert [p["id"] for p in client.get(f"/projects/{project_id}/ux-prompts").json()] == [bid]

    other = client.post("/projects", json={"name": f"pytest-ux-other-{uuid.uuid4().hex[:8]}"}).json()["id"]
    assert client.patch(f"/projects/{other}/ux-prompts/{bid}", json={"edited_text": "x"}).status_code == 404

    with get_session() as s:
        review.fork_new_version(s, s.query(Document).filter(Document.id == ids["doc"]).one())
    prompts = client.get(f"/projects/{project_id}/ux-prompts").json()
    assert prompts[0]["is_stale"] is True
    with get_session() as s:
        assert s.query(UxPrompt).filter(UxPrompt.id == bid).one().is_stale is True
        assert s.query(Project).filter(Project.id == project_id).one().style_brief is not None


# ── Reference style extraction endpoint ──────────────────────────────────────

def test_style_extraction_endpoint_reads_a_page_and_does_not_save(client, project_id, monkeypatch):
    monkeypatch.setattr(
        style_reference,
        "fetch_style_reference",
        lambda url: {"url": url, "title": "Ref", "style_tags": {"fonts": ["Inter"]}, "notes": []},
    )
    # the router imported the name directly, so patch it there too
    from app.routers import ux_prompts as router_module

    monkeypatch.setattr(router_module, "fetch_style_reference", style_reference.fetch_style_reference)
    r = client.post(f"/projects/{project_id}/ux-prompts/style-references/extract", json={"url": "https://example.com"})
    assert r.status_code == 200 and r.json()["style_tags"]["fonts"] == ["Inter"]
    assert "reference_styles" not in _sources(client, project_id)["style_brief"]


def test_style_extraction_endpoint_refuses_internal_addresses(client, project_id):
    r = client.post(
        f"/projects/{project_id}/ux-prompts/style-references/extract",
        json={"url": "http://169.254.170.2/v2/credentials"},
    )
    assert r.status_code == 422


# ── Dependencies worked out at approval ──────────────────────────────────────
# Confirmed live: dependencies were only worked out with the blueprint, and the
# "never guess" prompt found one dependency among 11 epics. They are now worked
# out when a version is approved, with reasons, and between stories too.

def _relations_with_reasons(llm):
    llm.relations = [
        {"epic_external_id": "E1", "depends_on": [], "integrates": []},
        {"epic_external_id": "E2", "depends_on": [{"epic": "E1", "reason": "reports on the hierarchy created in E1"}],
         "integrates": []},
    ]
    llm.story_relations = [
        {"story": "S2", "depends_on": "S1", "reason": "edits the hierarchy S1 creates"},
        {"story": "S3", "depends_on": "S1", "reason": "the report lists hierarchy items"},
        {"story": "S3", "depends_on": "S3", "reason": "self - dropped"},
        {"story": "S9", "depends_on": "S1", "reason": "unknown story - dropped"},
        {"story": "S2", "depends_on": "S1", "reason": "duplicate - dropped"},
    ]


def test_approving_a_version_works_out_its_dependencies(client, project_id, llm):
    _relations_with_reasons(llm)
    ids = _seed(project_id, approved=False)

    r = client.post(f"/projects/{project_id}/requirements/{ids['doc']}/approve")
    assert r.status_code == 200, r.text

    body = _sources(client, project_id)
    assert body["has_dependency_map"] is True
    assert body["has_blueprint"] is False  # no blueprint needed any more
    e2 = next(f for f in body["feature_map"] if f["epic_external_id"] == "E2")
    assert e2["depends_on"] == ["E1"]
    assert e2["depends_on_reasons"] == {"E1": "reports on the hierarchy created in E1"}
    assert body["suggested_order"] == ["E1", "E2"]
    assert [(d["story_external_id"], d["depends_on"]) for d in body["story_dependencies"]] == [("S2", "S1"), ("S3", "S1")]
    assert body["story_dependencies"][0]["reason"] == "edits the hierarchy S1 creates"
    assert len(_ai_calls(project_id)) == 1


def test_approval_stands_when_the_dependency_call_fails(client, project_id, llm):
    ids = _seed(project_id, approved=False)
    llm.client.chat.completions.create.side_effect = RuntimeError("OpenAI is down")

    r = client.post(f"/projects/{project_id}/requirements/{ids['doc']}/approve")

    assert r.status_code == 200, r.text
    assert r.json()["approval_status"] == "approved"
    assert _sources(client, project_id)["has_dependency_map"] is False


def test_dependencies_can_be_worked_out_for_a_version_approved_earlier(client, project_id, llm):
    _relations_with_reasons(llm)
    _seed(project_id)  # approved before dependencies were stored per version
    assert _sources(client, project_id)["has_dependency_map"] is False

    r = client.post(f"/projects/{project_id}/ux-prompts/dependencies")

    assert r.status_code == 200, r.text
    assert r.json()["has_dependency_map"] is True
    assert r.json()["suggested_order"] == ["E1", "E2"]
    assert _sources(client, project_id)["story_dependencies"]


def test_working_out_dependencies_needs_an_approved_version(client, project_id):
    _seed(project_id, approved=False)
    r = client.post(f"/projects/{project_id}/ux-prompts/dependencies")
    assert r.status_code == 409


def test_blueprint_reuses_the_dependencies_worked_out_at_approval(client, project_id, llm):
    _relations_with_reasons(llm)
    ids = _seed(project_id, approved=False)
    client.post(f"/projects/{project_id}/requirements/{ids['doc']}/approve")
    calls_after_approval = llm.call_count

    assert _blueprint(client, project_id, ids).status_code == 201

    relationship_calls = [
        c for c in llm.client.chat.completions.create.call_args_list[calls_after_approval:]
        if c.kwargs.get("tools") and c.kwargs["tools"][0]["function"]["name"] == "record_feature_relationships"
    ]
    assert relationship_calls == []
    assert _sources(client, project_id)["suggested_order"] == ["E1", "E2"]


def test_the_relationship_prompt_asks_for_reasons_and_story_dependencies(client, project_id, llm):
    from ai.text.ux_prompt_generator import _RELATIONSHIPS_SYSTEM_PROMPT, _RELATIONSHIPS_TOOL

    assert "an empty list is a correct answer" not in _RELATIONSHIPS_SYSTEM_PROMPT
    assert "story_dependencies" in _RELATIONSHIPS_SYSTEM_PROMPT
    params = _RELATIONSHIPS_TOOL["function"]["parameters"]
    assert params["required"] == ["features", "story_dependencies"]
    assert "reason" in params["properties"]["features"]["items"]["properties"]["depends_on"]["items"]["properties"]


# ── Dependencies in the prompts themselves ───────────────────────────────────
# The context pack used to read the map saved with the blueprint, so dependencies
# worked out later (at approval, or on request) reached the page but not the
# prompts; reasons and story-level dependencies never reached them at all.

def test_feature_prompt_uses_the_versions_dependencies_with_reasons(client, project_id, llm):
    ids = _seed(project_id)
    assert _blueprint(client, project_id, ids).status_code == 201  # its map has no dependencies
    _relations_with_reasons(llm)
    client.post(f"/projects/{project_id}/ux-prompts/dependencies")  # worked out after the blueprint

    _feature(client, project_id, ids, epic="e1", story_keys=("s1", "s2"))
    _feature(client, project_id, ids, epic="e2", story_keys=("s3",))

    sent = llm.prompt_requests()[-1]
    assert "E1 Strategy hierarchy (reports on the hierarchy created in E1): screens E1 List (/e1/list)" in sent


def test_feature_prompt_says_where_each_needed_story_stands(client, project_id, llm):
    _relations_with_reasons(llm)  # S2 needs S1, S3 needs S1
    ids = _seed(project_id, approved=False)
    client.post(f"/projects/{project_id}/requirements/{ids['doc']}/approve")
    _blueprint(client, project_id, ids)

    _feature(client, project_id, ids, epic="e1", story_keys=("s2",))
    assert "- S2 needs S1 Create hierarchy (edits the hierarchy S1 creates): not designed yet" in llm.prompt_requests()[-1]

    _feature(client, project_id, ids, epic="e1", story_keys=("s1", "s2"))
    assert "- S2 needs S1 Create hierarchy (edits the hierarchy S1 creates): in this prompt" in llm.prompt_requests()[-1]

    _feature(client, project_id, ids, epic="e2", story_keys=("s3",))
    assert (
        "- S3 needs S1 Create hierarchy (the report lists hierarchy items): already designed - link to it "
        "(screens: E1 List (/e1/list))"
    ) in llm.prompt_requests()[-1]


def test_feature_prompt_without_story_dependencies_has_no_story_section(client, project_id, llm):
    ids = _seed(project_id)
    _blueprint(client, project_id, ids)
    _feature(client, project_id, ids, epic="e1", story_keys=("s1",))
    assert "Story dependencies" not in llm.prompt_requests()[-1]
