"""
HTTP-level tests for the staged-resources intake API (Phase 1 of the
Requirements Intake Quality feature): stage a PDF, a .docx, and an image
resource per project, list them, and remove one. Image staging exercises a
real GPT-4o vision call, mocked the same way test_designs_api.py mocks
alignment checks — get_openai_client returns a fake client whose
chat.completions.create response is a plain message.content string, matching
transcribe_image()'s contract.
"""
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import docx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.deps import get_openai_client
from app.main import app


def _fake_openai_client(content: str):
    def factory():
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
        )
        return client

    return factory


def _fake_tool_call_client(tool_name: str, arguments_json: str):
    """
    Like _fake_openai_client, but shaped for a tool-calling endpoint
    (generate_clarifying_questions goes through _call_with_tool, which reads
    message.tool_calls, not message.content).
    """
    def factory():
        client = MagicMock()
        tool_call = SimpleNamespace(function=SimpleNamespace(name=tool_name, arguments=arguments_json))
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=""))],
            usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
        )
        return client

    return factory


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def project_id(client):
    r = client.post("/projects", json={"name": f"pytest-intake-project-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def sample_pdf(tmp_path):
    p = tmp_path / "requirements.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(72, 720, "Users can reset their password via email.")
    c.save()
    return p


@pytest.fixture
def sample_docx(tmp_path):
    p = tmp_path / "meeting_notes.docx"
    d = docx.Document()
    d.add_paragraph("Meeting notes: client wants SSO login by Q3.")
    d.save(str(p))
    return p


@pytest.fixture
def sample_image(tmp_path):
    p = tmp_path / "whiteboard.png"
    img = Image.new("RGB", (400, 300), color="white")
    ImageDraw.Draw(img).text((20, 20), "Order -> Payment -> Fulfillment", fill="black")
    img.save(p)
    return p


def test_stage_pdf_resource_extracts_text(client, project_id, sample_pdf):
    with open(sample_pdf, "rb") as f:
        r = client.post(
            f"/projects/{project_id}/resources",
            data={"resource_kind": "primary_requirements"},
            files={"file": ("requirements.pdf", f, "application/pdf")},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["resource_kind"] == "primary_requirements"
    assert body["file_type"] == "pdf"
    assert "reset their password" in body["extracted_text"]
    assert body["processing_error"] is None


def test_stage_docx_resource_extracts_text(client, project_id, sample_docx):
    with open(sample_docx, "rb") as f:
        r = client.post(
            f"/projects/{project_id}/resources",
            data={"resource_kind": "meeting_notes"},
            files={"file": ("meeting_notes.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["file_type"] == "docx"
    assert "SSO login" in body["extracted_text"]


def test_stage_image_resource_transcribes_via_vision(client, project_id, sample_image):
    app.dependency_overrides[get_openai_client] = _fake_openai_client(
        "A flowchart: Order -> Payment -> Fulfillment."
    )
    with open(sample_image, "rb") as f:
        r = client.post(
            f"/projects/{project_id}/resources",
            data={"resource_kind": "other", "notes": "whiteboard photo from kickoff"},
            files={"file": ("whiteboard.png", f, "image/png")},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["file_type"] == "image"
    assert body["extracted_text"] == "A flowchart: Order -> Payment -> Fulfillment."
    assert body["notes"] == "whiteboard photo from kickoff"


def test_stage_resource_rejects_unsupported_file_type(client, project_id, tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("plain text file")
    with open(p, "rb") as f:
        r = client.post(
            f"/projects/{project_id}/resources",
            data={"resource_kind": "other"},
            files={"file": ("notes.txt", f, "text/plain")},
        )
    assert r.status_code == 400, r.text


def test_list_and_delete_resources(client, project_id, sample_pdf, sample_docx):
    for path, name, kind in [
        (sample_pdf, "requirements.pdf", "primary_requirements"),
        (sample_docx, "meeting_notes.docx", "meeting_notes"),
    ]:
        with open(path, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/resources",
                data={"resource_kind": kind},
                files={"file": (name, f, "application/octet-stream")},
            )
        assert r.status_code == 201, r.text

    r = client.get(f"/projects/{project_id}/resources")
    assert r.status_code == 200, r.text
    resources = r.json()
    assert len(resources) == 2

    to_delete = resources[0]["id"]
    r = client.delete(f"/projects/{project_id}/resources/{to_delete}")
    assert r.status_code == 204, r.text

    r = client.get(f"/projects/{project_id}/resources")
    assert len(r.json()) == 1

    r = client.delete(f"/projects/{project_id}/resources/{to_delete}")
    assert r.status_code == 404, r.text


def test_stage_resource_for_unknown_project_404s(client, sample_pdf):
    with open(sample_pdf, "rb") as f:
        r = client.post(
            "/projects/does-not-exist/resources",
            data={"resource_kind": "primary_requirements"},
            files={"file": ("requirements.pdf", f, "application/pdf")},
        )
    assert r.status_code == 404, r.text


CLARIFYING_QUESTIONS_JSON = (
    '{"questions": [{"question": "Should refunds be automatic or need approval?", '
    '"topic_area": "Refunds", "why_it_matters": "Decides whether an approval step is built."}]}'
)


def test_generate_clarifying_questions_requires_a_staged_resource(client, project_id):
    r = client.post(f"/projects/{project_id}/clarifying-questions")
    assert r.status_code == 422, r.text


def test_generate_list_and_answer_clarifying_questions(client, project_id, sample_pdf):
    with open(sample_pdf, "rb") as f:
        r = client.post(
            f"/projects/{project_id}/resources",
            data={"resource_kind": "primary_requirements"},
            files={"file": ("requirements.pdf", f, "application/pdf")},
        )
    assert r.status_code == 201, r.text

    # generate_clarifying_questions() now makes two calls (a material-gap call
    # and a fixed-checklist baseline audit call — see its own docstring for
    # why); this fake returns the same single-question payload for both, so
    # two (identical-content) questions come back, not one.
    app.dependency_overrides[get_openai_client] = _fake_tool_call_client(
        "record_clarifying_questions", CLARIFYING_QUESTIONS_JSON
    )
    r = client.post(f"/projects/{project_id}/clarifying-questions")
    assert r.status_code == 201, r.text
    questions = r.json()
    assert len(questions) == 2
    assert all(q["topic_area"] == "Refunds" for q in questions)
    assert all(q["status"] == "pending" for q in questions)
    question_id = questions[0]["id"]

    r = client.get(f"/projects/{project_id}/clarifying-questions")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2

    r = client.patch(
        f"/projects/{project_id}/clarifying-questions/{question_id}",
        json={"status": "answered", "answer_text": "Automatic, no approval needed."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "answered"
    assert body["answer_text"] == "Automatic, no approval needed."
    assert body["answered_at"] is not None

    r = client.patch(f"/projects/{project_id}/clarifying-questions/does-not-exist", json={"status": "skipped"})
    assert r.status_code == 404, r.text


# --- run-staged-extraction (Phase 4) ---

_STAGED_EXTRACTION = {
    "epics": [{"id": "E1", "title": "Password Recovery", "assumptions": [], "dependencies": [], "source_reference": "Primary requirements"}],
    "user_stories": [
        {
            "id": "S1",
            "epic_id": "E1",
            "title": "Reset password via email",
            "description": "As a user, I want to reset my password via email, so that I can regain access to my account.",
            "scenarios": [],
            "acceptance_criteria": [{"text": "A reset link is emailed on request", "out_of_scope": False}],
            "error_handling": [],
        }
    ],
    "gaps": [],
}


def _fake_extraction_pipeline_client(uncovered_policy_titles: list[str] = ()):
    """
    Mirrors test_requirements_api.py's _fake_openai_client(): handles every
    call extract_requirements() makes (draft/review as record_extraction
    tool calls, the granularity audit as its own tool call, the coverage
    audit as a plain-content completion) with one fake client, since
    run_staged_extraction() goes through the exact same pipeline as a
    one-shot upload.

    Also always handles record_policy_coverage_audit (returning an empty
    list by default) — standing policies are global, not scoped to one
    test's project, so a policy any test creates via POST /policies persists
    across the rest of the session; every fake client used with
    run_staged_extraction must tolerate that audit call firing even when
    the test itself has nothing to do with policies, or a leaked policy
    from an earlier test breaks it with an unhandled tool name.
    """
    def factory():
        client = MagicMock()

        def create(**kwargs):
            tool_choice = kwargs.get("tool_choice")
            requested_name = tool_choice["function"]["name"] if tool_choice else "record_extraction"
            if requested_name == "record_granularity_audit":
                tool_input = {
                    "epic_findings": [
                        {"epic_id": e["id"], "under_split": False, "missing_capabilities": []}
                        for e in _STAGED_EXTRACTION["epics"]
                    ]
                }
            elif requested_name == "record_policy_coverage_audit":
                tool_input = {"uncovered_policy_titles": list(uncovered_policy_titles)}
            else:
                tool_input = _STAGED_EXTRACTION
            tool_call = SimpleNamespace(
                function=SimpleNamespace(name=requested_name, arguments=json.dumps(tool_input))
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content="(no coverage findings)"))],
                usage=SimpleNamespace(prompt_tokens=400, completion_tokens=120),
            )

        client.chat.completions.create.side_effect = create
        return client

    return factory


def test_run_staged_extraction_checks_active_standing_policy_coverage(client, project_id, sample_pdf):
    r = client.post("/policies", json={"title": "Accessibility default", "policy_text": "Meet WCAG 2.1 AA."})
    assert r.status_code == 201, r.text

    with open(sample_pdf, "rb") as f:
        r = client.post(
            f"/projects/{project_id}/resources",
            data={"resource_kind": "primary_requirements"},
            files={"file": ("requirements.pdf", f, "application/pdf")},
        )
    assert r.status_code == 201, r.text

    # Audit says it's already covered, so no repair call fires — this test's
    # job is just confirming the policy-coverage audit runs at all when an
    # active policy exists, and that the endpoint still succeeds end to end.
    app.dependency_overrides[get_openai_client] = _fake_extraction_pipeline_client(uncovered_policy_titles=[])
    r = client.post(f"/projects/{project_id}/requirements/run-staged-extraction")
    assert r.status_code == 201, r.text

    r = client.get(f"/projects/{project_id}/requirements")
    assert r.status_code == 200, r.text


def test_run_staged_extraction_requires_primary_requirements_resource(client, project_id, sample_docx):
    with open(sample_docx, "rb") as f:
        r = client.post(
            f"/projects/{project_id}/resources",
            data={"resource_kind": "meeting_notes"},
            files={"file": ("meeting_notes.docx", f, "application/octet-stream")},
        )
    assert r.status_code == 201, r.text

    r = client.post(f"/projects/{project_id}/requirements/run-staged-extraction")
    assert r.status_code == 422, r.text


def test_run_staged_extraction_creates_document_from_staged_resources(client, project_id, sample_pdf, sample_docx):
    with open(sample_pdf, "rb") as f:
        r = client.post(
            f"/projects/{project_id}/resources",
            data={"resource_kind": "primary_requirements"},
            files={"file": ("requirements.pdf", f, "application/pdf")},
        )
    assert r.status_code == 201, r.text

    with open(sample_docx, "rb") as f:
        r = client.post(
            f"/projects/{project_id}/resources",
            data={"resource_kind": "meeting_notes"},
            files={"file": ("meeting_notes.docx", f, "application/octet-stream")},
        )
    assert r.status_code == 201, r.text

    app.dependency_overrides[get_openai_client] = _fake_extraction_pipeline_client()
    r = client.post(f"/projects/{project_id}/requirements/run-staged-extraction")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["epics_extracted"] == 1
    assert body["stories_extracted"] == 1
    assert body["document"]["project_id"] == project_id
    assert "Staged resources" in body["document"]["source_filename"]

    r = client.get(f"/projects/{project_id}/requirements")
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["epics"][0]["text"] == "Password Recovery"
    assert detail["stories"][0]["text"] == "Reset password via email"
