"""
Tests for the on-demand requirements evaluation endpoint
(POST /projects/{project_id}/requirements/{doc_id}/evaluate) — see
backend/app/services/requirements_evaluation.py. Directly seeds a Document +
RequirementItem/Gap rows via get_session() (matching
test_create_requirement_item.py's pattern) rather than running the full
upload/extraction pipeline, since evaluation only reads what's already
persisted. OpenAI is mocked throughout.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db.models import AiCall, Document, EvaluationReport, Gap, Project, RequirementItem
from app.db.session import get_session
from app.deps import get_openai_client
from app.main import app

SOURCE_REVIEW_PAYLOAD = {
    "clarity_score": 62,
    "summary": "Source material is workable but leaves several behaviors unstated.",
    "issues": ["Section 2 never defines what counts as a 'valid' submission."],
}
OUTPUT_REVIEW_PAYLOAD = {
    "specificity_score": 70,
    "summary": "Stories are mostly concrete, one is generic.",
    "weak_items": [{"external_id": "S2", "reason": "Acceptance criteria just restate the title."}],
}
ARTIFACT_REVIEW_PAYLOAD = {
    "artifact_quality_score": 55,
    "summary": "One gap is vague; the accepted suggestion is genuinely useful.",
    "issues": ["Gap on 'error handling' doesn't name which errors are unhandled."],
}


def _fake_evaluation_client(fail_tool: str | None = None):
    def factory():
        client = MagicMock()

        def create(**kwargs):
            tool_choice = kwargs["tool_choice"]
            name = tool_choice["function"]["name"]
            if fail_tool and name == fail_tool:
                raise RuntimeError("simulated API failure")
            payload = {
                "record_source_material_review": SOURCE_REVIEW_PAYLOAD,
                "record_output_story_review": OUTPUT_REVIEW_PAYLOAD,
                "record_artifact_quality_review": ARTIFACT_REVIEW_PAYLOAD,
            }[name]
            tool_call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(payload)))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=""))],
                usage=SimpleNamespace(prompt_tokens=300, completion_tokens=100),
            )

        client.chat.completions.create.side_effect = create
        return client

    return factory


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_pdf(tmp_path):
    p = tmp_path / "requirements.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(72, 720, "Users can submit a claim for review.")
    c.save()
    return p


@pytest.fixture
def seeded_document(sample_pdf):
    """
    One epic, two stories (one plain, one standing-policy-derived), one gap
    (open, high severity), three ai_suggestion rows (pending/accepted/
    dismissed — all three must count toward suggestion_count_total
    regardless of status).
    """
    with get_session() as s:
        project = Project(name="pytest-evaluation-project")
        s.add(project)
        s.flush()
        doc = Document(
            project_id=project.id,
            doc_type="requirement",
            version=1,
            approval_status="draft",
            source_filename="requirements.pdf",
            source_file_path=str(sample_pdf),
        )
        s.add(doc)
        s.flush()

        epic = RequirementItem(document_id=doc.id, type="epic", external_id="E1", text="Claims")
        s.add(epic)
        s.flush()

        story1 = RequirementItem(
            document_id=doc.id, type="story", external_id="S1", parent_id=epic.id,
            text="Submit a claim", description="As a user, I want to submit a claim.",
            acceptance_criteria=[{"text": "A claim can be submitted", "out_of_scope": False}],
        )
        story2 = RequirementItem(
            document_id=doc.id, type="story", external_id="S2", parent_id=epic.id,
            text="Accessible claim form",
            description="As a user, I want the claim form to be accessible.",
            acceptance_criteria=[{"text": "The form meets WCAG 2.1 AA", "out_of_scope": False}],
            source_reference="TKMiND Standard Policy — Accessibility default",
        )
        s.add_all([story1, story2])

        gap = Gap(document_id=doc.id, description="Error handling is unclear.", severity="high", status="open")
        s.add(gap)

        suggestion_pending = RequirementItem(
            document_id=doc.id, type="story", external_id="S3", parent_id=epic.id,
            text="Pending suggestion", description="A suggested story.",
            acceptance_criteria=[], origin="ai_suggestion", suggestion_status="pending",
        )
        suggestion_accepted = RequirementItem(
            document_id=doc.id, type="story", external_id="S4", parent_id=epic.id,
            text="Accepted suggestion", description="A suggested story that was accepted.",
            acceptance_criteria=[], origin="ai_suggestion", suggestion_status="accepted",
        )
        suggestion_dismissed = RequirementItem(
            document_id=doc.id, type="story", external_id="S5", parent_id=epic.id,
            text="Dismissed suggestion", description="A suggested story that was dismissed.",
            acceptance_criteria=[], origin="ai_suggestion", suggestion_status="dismissed",
        )
        s.add_all([suggestion_pending, suggestion_accepted, suggestion_dismissed])

        ids = (project.id, doc.id)

    yield ids

    _cleanup(*ids)


def _cleanup(project_id, doc_id):
    with get_session() as s:
        s.query(AiCall).filter(AiCall.document_id == doc_id).delete()
        s.query(EvaluationReport).filter(EvaluationReport.document_id == doc_id).delete()
        s.query(Gap).filter(Gap.document_id == doc_id).delete()
        s.query(RequirementItem).filter(RequirementItem.document_id == doc_id).delete()
    with get_session() as s:
        d = s.query(Document).filter(Document.id == doc_id).first()
        if d:
            s.delete(d)
    with get_session() as s:
        p = s.query(Project).filter(Project.id == project_id).first()
        if p:
            s.delete(p)


def test_evaluation_is_null_before_ever_run(client, seeded_document):
    project_id, doc_id = seeded_document
    r = client.get(f"/projects/{project_id}/requirements/{doc_id}")
    assert r.status_code == 200, r.text
    assert r.json()["evaluation"] is None


def test_run_evaluation_computes_scores_signals_and_logs_ai_calls(client, seeded_document):
    project_id, doc_id = seeded_document
    app.dependency_overrides[get_openai_client] = _fake_evaluation_client()

    r = client.post(f"/projects/{project_id}/requirements/{doc_id}/evaluate")
    assert r.status_code == 200, r.text
    evaluation = r.json()["evaluation"]
    assert evaluation is not None
    assert 0 <= evaluation["input_quality_score"] <= 100
    assert 0 <= evaluation["output_quality_score"] <= 100
    # the three agents' own raw scores, stored alongside the blended ones —
    # match the canned fake-client payloads above exactly (62/70/55).
    assert evaluation["source_material_score"] == 62
    assert evaluation["stories_score"] == 70
    assert evaluation["advisory_content_score"] == 55

    signals = evaluation["signals"]
    assert signals["total_epic_count"] == 1
    # visible stories only: S1, S2 (the ai_suggestion-origin ones are excluded
    # from the visible tree, matching _detail_for's own definition) — plus
    # suggestion_accepted (S4) IS visible since accepted suggestions join the
    # real tree.
    assert signals["total_story_count"] == 3  # S1, S2, S4
    assert signals["gap_count"] == 1
    assert signals["high_severity_gap_count"] == 1
    assert signals["open_gap_count"] == 1
    assert signals["open_high_severity_gap_count"] == 1
    # all three ai_suggestion rows count regardless of status
    assert signals["suggestion_count_total"] == 3
    assert signals["suggestion_accepted_count"] == 1
    assert signals["policy_derived_count"] == 1  # S2

    assert evaluation["weak_story_ids"] == ["S2"]
    # key_findings is now a list of {category, text} — one of the three
    # fixed categories every finding is tagged with, so a PM can trace it
    # back to what it's about.
    finding_categories = {f["category"] for f in evaluation["key_findings"]}
    assert finding_categories <= {"Source material", "Stories", "Advisory content"}
    assert any("S2" in f["text"] for f in evaluation["key_findings"])
    assert any(
        f["category"] == "Advisory content" and "error handling" in f["text"].lower()
        for f in evaluation["key_findings"]
    )
    assert any("open gap" in r.lower() for r in evaluation["recommendations"])

    with get_session() as s:
        call_types = {
            row.call_type
            for row in s.query(AiCall).filter(AiCall.document_id == doc_id).all()
        }
    assert call_types == {"source_material_review", "output_story_review", "artifact_quality_review"}


def test_run_evaluation_upserts_single_row(client, seeded_document):
    project_id, doc_id = seeded_document
    app.dependency_overrides[get_openai_client] = _fake_evaluation_client()

    r1 = client.post(f"/projects/{project_id}/requirements/{doc_id}/evaluate")
    assert r1.status_code == 200, r1.text
    report_id_1 = r1.json()["evaluation"]["id"]

    r2 = client.post(f"/projects/{project_id}/requirements/{doc_id}/evaluate")
    assert r2.status_code == 200, r2.text
    report_id_2 = r2.json()["evaluation"]["id"]

    assert report_id_1 == report_id_2  # same row, not a new one

    with get_session() as s:
        count = s.query(EvaluationReport).filter(EvaluationReport.document_id == doc_id).count()
        ai_call_count = s.query(AiCall).filter(AiCall.document_id == doc_id).count()
    assert count == 1
    assert ai_call_count == 6  # 3 calls x 2 runs


def test_evaluate_unknown_document_404s(client, seeded_document):
    project_id, _doc_id = seeded_document
    app.dependency_overrides[get_openai_client] = _fake_evaluation_client()
    r = client.post(f"/projects/{project_id}/requirements/does-not-exist/evaluate")
    assert r.status_code == 404, r.text


def test_evaluate_surfaces_api_error_as_502(client, seeded_document):
    project_id, doc_id = seeded_document
    app.dependency_overrides[get_openai_client] = _fake_evaluation_client(fail_tool="record_artifact_quality_review")
    r = client.post(f"/projects/{project_id}/requirements/{doc_id}/evaluate")
    assert r.status_code == 502, r.text
    assert "try running the evaluation again" in r.text
