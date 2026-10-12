"""
Tests for use_case_diagrams.py (per-story UML use-case diagrams): PlantUML
text generation and sanitizing, the plain fallback, content-hash caching, AI
call logging, graceful degradation, and that the PDF / Confluence page carry
the diagram. The model and PlantUML renderer are stubbed — no OpenAI, no Java.
"""
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage

from app.db.models import AiCall, Document, Project, RequirementItem, UseCaseDiagram
from app.db.session import SessionLocal
from app.services import plantuml_renderer, use_case_diagrams
from app.services.business_document import build_business_document
from app.services.confluence_export import build_version_page_html, publish_requirements_version
from app.services.pdf_export import generate_business_pdf


def _png(width=600, height=300) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def _story(**kwargs) -> RequirementItem:
    defaults = dict(
        id="s1",
        type="story",
        external_id="S1",
        text="Edit profile",
        description="As a startup, I want to edit my profile, so that investors see current details.",
    )
    return RequirementItem(**{**defaults, **kwargs})


class _FakeLlm:
    """Stands in for the OpenAI client; counts calls."""

    def __init__(self, spec=None, fail=False):
        self.calls = 0
        self._spec = spec or {
            "primary_actor": "Startup",
            "secondary_actors": ["Investor"],
            "main_use_case": "Edit company profile",
            "includes": ["Validate fields"],
            "extends": ["Show save error"],
        }
        self._fail = fail
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        if self._fail:
            raise RuntimeError("model down")
        call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(self._spec)))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200),
        )


@pytest.fixture
def renderer(monkeypatch):
    """Pretend PlantUML is installed; 'render' returns a tiny PNG per text."""
    rendered: list[list[str]] = []

    def fake_render(texts):
        rendered.append(list(texts))
        return {t: _png() for t in texts}

    monkeypatch.setattr(plantuml_renderer, "is_available", lambda: True)
    monkeypatch.setattr(plantuml_renderer, "render_png_many", fake_render)
    return rendered


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _persisted(db, *stories):
    project = Project(name="Acme Portal")
    db.add(project)
    db.flush()
    doc = Document(project_id=project.id, doc_type="requirement", version=1, approval_status="approved", source_filename="x.pdf")
    db.add(doc)
    db.flush()
    for s in stories:
        s.document_id = doc.id
        db.add(s)
    db.flush()
    return project, doc


# --- PlantUML text ---

def test_plantuml_has_actors_boundary_include_and_extend():
    text = use_case_diagrams.build_plantuml(
        {
            "primary_actor": "Startup",
            "secondary_actors": ["Investor"],
            "main_use_case": "Edit company profile",
            "includes": ["Validate fields"],
            "extends": ["Show save error"],
        },
        "Acme Portal",
    )
    assert text.startswith("@startuml") and text.rstrip().endswith("@enduml")
    assert 'actor "Startup" as A0' in text
    assert 'actor "Investor" as A1' in text
    assert 'rectangle "Acme Portal" {' in text
    assert "A0 --> UC0" in text and "UC0 -- A1" in text
    assert "UC0 ..> UC1 : <<include>>" in text
    assert "UC2 ..> UC0 : <<extend>>" in text


def test_plantuml_labels_cannot_inject_directives():
    text = use_case_diagrams.build_plantuml(
        {"primary_actor": 'Evil"\n!include /etc/passwd', "main_use_case": 'x"\n@enduml\n@startuml'},
        'Sys"\n!include /etc/hosts',
    )
    # Newlines are stripped, so injected text stays inside a quoted label and
    # can never start a line of its own.
    lines = text.splitlines()
    assert [l for l in lines if l.startswith("@")] == ["@startuml", "@enduml"]
    assert not any(l.startswith("!") for l in lines)
    assert all(l.count('"') % 2 == 0 for l in lines)


def test_long_labels_are_wrapped_and_shortened():
    text = use_case_diagrams.build_plantuml(
        {"primary_actor": "User", "main_use_case": "word " * 60}, "S"
    )
    line = next(l for l in text.splitlines() if "as UC0" in l)
    assert "\\n" in line and len(line) < 200


def test_spec_is_normalised_and_deduplicated():
    spec = use_case_diagrams.normalise_spec(
        {
            "primary_actor": "  Startup ",
            "secondary_actors": ["startup", "Investor", "Investor", "", "A", "B", "C"],
            "main_use_case": "Edit",
            "includes": ["Edit", "Validate", "validate"],
            "extends": [],
        }
    )
    assert spec["primary_actor"] == "Startup"
    assert spec["secondary_actors"] == ["Investor", "A", "B"]
    assert spec["includes"] == ["Validate"]


# --- fallback ---

def test_fallback_uses_the_user_story_role_and_capability():
    spec = use_case_diagrams.fallback_spec(_story())
    assert spec["primary_actor"] == "Startup"
    assert spec["main_use_case"] == "Edit my profile"
    assert spec["includes"] == [] and spec["extends"] == []


def test_fallback_without_a_user_story_uses_title():
    spec = use_case_diagrams.fallback_spec(_story(description=None))
    assert spec["primary_actor"] == "User" and spec["main_use_case"] == "Edit profile"


# --- ensure_diagrams ---

def test_nothing_happens_without_plantuml(db, monkeypatch):
    monkeypatch.setattr(plantuml_renderer, "is_available", lambda: False)
    llm = _FakeLlm()
    project, doc = _persisted(db, _story())
    assert use_case_diagrams.ensure_diagrams(db, doc, project, [_story()], llm) == {}
    assert llm.calls == 0  # no tokens spent when nothing can be rendered


def test_generates_caches_and_logs_the_ai_call(db, renderer):
    story = _story()
    project, doc = _persisted(db, story)
    llm = _FakeLlm()

    result = use_case_diagrams.ensure_diagrams(db, doc, project, [story], llm)
    assert set(result) == {story.id} and result[story.id].startswith(b"\x89PNG")
    assert llm.calls == 1
    assert db.query(UseCaseDiagram).count() == 1
    call = db.query(AiCall).filter(AiCall.call_type == "use_case_diagram").one()
    assert (call.document_id, call.input_tokens, call.output_tokens) == (doc.id, 1000, 200)
    assert float(call.estimated_cost_usd) > 0
    assert "Show save error" in renderer[0][0]

    # Second export of the same content: served from the cache, no model call.
    use_case_diagrams.ensure_diagrams(db, doc, project, [story], llm)
    assert llm.calls == 1


def test_unchanged_story_in_a_new_version_reuses_the_cached_spec(db, renderer):
    story = _story()
    project, doc = _persisted(db, story)
    llm = _FakeLlm()
    use_case_diagrams.ensure_diagrams(db, doc, project, [story], llm)

    copied = _story(id="s1-v2")  # same content, new row id (as fork_new_version makes)
    use_case_diagrams.ensure_diagrams(db, doc, project, [copied], llm)
    assert llm.calls == 1


def test_edited_story_is_regenerated(db, renderer):
    story = _story()
    project, doc = _persisted(db, story)
    llm = _FakeLlm()
    use_case_diagrams.ensure_diagrams(db, doc, project, [story], llm)

    edited = _story(description="As a startup, I want to delete my profile, so that I can leave.")
    use_case_diagrams.ensure_diagrams(db, doc, project, [edited], llm)
    assert llm.calls == 2


def test_model_failure_falls_back_and_is_not_cached(db, renderer):
    story = _story()
    project, doc = _persisted(db, story)
    result = use_case_diagrams.ensure_diagrams(db, doc, project, [story], _FakeLlm(fail=True))
    assert story.id in result  # still drawn, from the fallback
    assert 'actor "Startup" as A0' in renderer[0][0]
    assert db.query(UseCaseDiagram).count() == 0
    assert db.query(AiCall).filter(AiCall.call_type == "use_case_diagram").count() == 0


def test_no_client_uses_fallback_without_calling_anything(db, renderer):
    story = _story()
    project, doc = _persisted(db, story)
    result = use_case_diagrams.ensure_diagrams(db, doc, project, [story], None)
    assert story.id in result and db.query(UseCaseDiagram).count() == 0


def test_a_story_that_fails_to_render_is_just_omitted(db, monkeypatch):
    monkeypatch.setattr(plantuml_renderer, "is_available", lambda: True)
    monkeypatch.setattr(plantuml_renderer, "render_png_many", lambda texts: {})
    story = _story()
    project, doc = _persisted(db, story)
    assert use_case_diagrams.ensure_diagrams(db, doc, project, [story], None) == {}


# --- exports carry the diagram ---

def _bdoc_with_diagram():
    project = Project(name="Acme Portal")
    doc = Document(id="d1", version=1, approval_status="approved", source_filename="sow.pdf")
    epic = RequirementItem(id="e1", type="epic", external_id="E1", text="Profiles")
    story = _story(parent_id="e1")
    bdoc = build_business_document(project, doc, [epic], [story], [])
    bdoc.diagrams = {story.id: _png()}
    return bdoc


def test_pdf_embeds_the_diagram():
    with_diagram = generate_business_pdf(_bdoc_with_diagram())
    bdoc = _bdoc_with_diagram()
    bdoc.diagrams = {}
    without = generate_business_pdf(bdoc)
    assert with_diagram.startswith(b"%PDF") and len(with_diagram) > len(without)


def test_confluence_page_references_the_attachment():
    html = build_version_page_html(_bdoc_with_diagram())
    assert "Use case diagram" in html
    assert '<ri:attachment ri:filename="use-case-S1.png"' in html
    bdoc = _bdoc_with_diagram()
    bdoc.diagrams = {}
    assert "Use case diagram" not in build_version_page_html(bdoc)


def test_publish_uploads_each_diagram_to_the_new_page():
    class Client:
        def __init__(self):
            self.attached = []

        def find_page_by_title(self, title):
            return {"id": "idx", "_links": {}} if "Requirements" in title and "v" not in title else None

        def create_page(self, title, body, parent_id=None):
            return {"id": "p1", "_links": {"webui": "/p1"}}

        def page_url(self, page):
            return "https://x/p1"

        def attach_file(self, page_id, filename, data, content_type="image/png"):
            self.attached.append((page_id, filename))

    class Session:
        def flush(self):
            pass

    client = Client()
    result = publish_requirements_version(Session(), client, Project(name="Acme Portal", confluence_metadata={"index_page_id": "idx"}), None, _bdoc_with_diagram())
    assert result["page_id"] == "p1"
    assert client.attached == [("p1", "use-case-S1.png")]


def test_failed_attachment_does_not_abort_publishing():
    class Client:
        def find_page_by_title(self, title):
            return None

        def create_page(self, title, body, parent_id=None):
            return {"id": "p1", "_links": {}}

        def page_url(self, page):
            return "https://x/p1"

        def attach_file(self, *args, **kwargs):
            raise RuntimeError("upload refused")

    class Session:
        def flush(self):
            pass

    project = Project(name="Acme Portal", confluence_metadata={"index_page_id": "idx"})
    result = publish_requirements_version(Session(), Client(), project, None, _bdoc_with_diagram())
    assert result["page_id"] == "p1"
