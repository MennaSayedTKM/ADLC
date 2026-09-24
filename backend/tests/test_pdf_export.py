"""
Tests for the requirements PDF export endpoint. No OpenAI/embed mocking
needed — this is a pure DB-read + reportlab-render endpoint.
"""
import pytest
from fastapi.testclient import TestClient

from app.db.models import Document, Gap, Project, RequirementItem
from app.db.session import get_session
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project_with_document():
    with get_session() as s:
        project = Project(name="pytest-pdf-export-project")
        s.add(project)
        s.flush()
        doc = Document(
            project_id=project.id,
            doc_type="requirement",
            version=1,
            approval_status="draft",
            source_filename="test.pdf",
        )
        s.add(doc)
        s.flush()
        epic = RequirementItem(
            document_id=doc.id, type="epic", external_id="E1", text="Auth", source_reference="4.1.A"
        )
        s.add(epic)
        s.flush()
        story = RequirementItem(
            document_id=doc.id,
            type="story",
            external_id="S1",
            parent_id=epic.id,
            text="As a user, I can log in.",
            acceptance_criteria=[{"text": "Shows an error on wrong password", "out_of_scope": False}],
            scenarios=[
                {
                    "title": "Login with valid credentials",
                    "given": "I am on the login page",
                    "when": "I submit a valid email and password",
                    "then": "I am redirected to the dashboard",
                    "source_reference": "4.1.A",
                }
            ],
            error_handling=[{"condition": "wrong password", "message": "Invalid email or password."}],
        )
        s.add(story)
        gap = Gap(document_id=doc.id, description="Unclear session timeout", severity="medium")
        s.add(gap)
        s.flush()
        ids = (project.id, doc.id)

    yield ids
    _cleanup(*ids)


def _cleanup(project_id, doc_id):
    with get_session() as s:
        for row in s.query(Gap).filter(Gap.document_id == doc_id):
            s.delete(row)
        for row in s.query(RequirementItem).filter(
            RequirementItem.document_id == doc_id, RequirementItem.parent_id.isnot(None)
        ):
            s.delete(row)
    with get_session() as s:
        for row in s.query(RequirementItem).filter(RequirementItem.document_id == doc_id):
            s.delete(row)
    with get_session() as s:
        d = s.query(Document).filter(Document.id == doc_id).first()
        if d:
            s.delete(d)
    with get_session() as s:
        p = s.query(Project).filter(Project.id == project_id).first()
        if p:
            s.delete(p)


def test_export_rejected_when_not_approved(client, project_with_document):
    project_id, doc_id = project_with_document
    r = client.get(f"/projects/{project_id}/requirements/{doc_id}/export.pdf")
    assert r.status_code == 400
    assert "approved" in r.json()["detail"].lower()


def _pdf_text(content: bytes) -> str:
    import fitz

    pdf = fitz.open(stream=content, filetype="pdf")
    text = "\n".join(page.get_text() for page in pdf)
    pdf.close()
    return text


def test_export_defaults_to_business_document(client, project_with_document):
    project_id, doc_id = project_with_document

    r = client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
    assert r.status_code == 200, r.text

    r = client.get(f"/projects/{project_id}/requirements/{doc_id}/export.pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    assert "pytest-pdf-export-project_business_requirements_v1.pdf" in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"

    text = _pdf_text(r.content)
    assert "Business Requirements Document" in text
    assert "Overview and Scope" in text
    assert "BR-1.1" in text
    assert "Ref S1" in text
    assert "Shows an error on wrong password" in text  # acceptance criteria kept
    assert "Open Issues Requiring Stakeholder Input" in text
    assert "Unclear session timeout" in text
    assert "Version History" in text
    assert "Stakeholder Sign-off" in text

    # delivery-team detail stays out of the stakeholder document
    assert "SCENARIOS" not in text
    assert "I am on the login page" not in text
    assert "Invalid email or password." not in text


def test_business_export_excludes_pending_suggestions(client, project_with_document):
    project_id, doc_id = project_with_document
    with get_session() as s:
        epic = s.query(RequirementItem).filter(
            RequirementItem.document_id == doc_id, RequirementItem.type == "epic"
        ).one()
        s.add(
            RequirementItem(
                document_id=doc_id,
                type="story",
                external_id="S2",
                parent_id=epic.id,
                text="Unreviewed AI suggestion",
                origin="ai_suggestion",
                suggestion_status="pending",
            )
        )

    r = client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
    assert r.status_code == 200, r.text

    for fmt in ("business", "delivery"):
        r = client.get(f"/projects/{project_id}/requirements/{doc_id}/export.pdf?format={fmt}")
        assert r.status_code == 200, r.text
        assert "Unreviewed AI suggestion" not in _pdf_text(r.content)


def test_export_rejects_unknown_format(client, project_with_document):
    project_id, doc_id = project_with_document
    client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
    r = client.get(f"/projects/{project_id}/requirements/{doc_id}/export.pdf?format=slides")
    assert r.status_code == 422


def test_delivery_export_keeps_story_detail(client, project_with_document):
    project_id, doc_id = project_with_document

    r = client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
    assert r.status_code == 200, r.text

    r = client.get(f"/projects/{project_id}/requirements/{doc_id}/export.pdf?format=delivery")
    assert r.status_code == 200, r.text
    assert "pytest-pdf-export-project_delivery_requirements_v1.pdf" in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 500  # a real rendered document, not an empty shell

    text = _pdf_text(r.content)

    assert "Shows an error on wrong password" in text
    assert "SCENARIOS" in text
    assert "Login with valid credentials" in text
    assert "I am on the login page" in text
    assert "I submit a valid email and password" in text
    assert "I am redirected to the dashboard" in text
    assert "ERROR HANDLING" in text
    assert "wrong password" in text
    assert "Invalid email or password." in text
    assert "4.1.A" in text  # source_reference rendered for both the epic and the scenario


def test_export_404_on_unknown_document(client, project_with_document):
    project_id, _doc_id = project_with_document
    r = client.get(f"/projects/{project_id}/requirements/does-not-exist/export.pdf")
    assert r.status_code == 404
