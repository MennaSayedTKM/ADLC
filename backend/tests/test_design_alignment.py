"""
DB-integration test for design_alignment.run_alignment_check(). OpenAI is
mocked; SQLite writes are real.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.db.models import (
    AiCall,
    AlignmentFinding,
    AlignmentReport,
    Document,
    Project,
    RequirementItem,
)
from app.db.session import get_session
from app.services.design_alignment import get_approved_stories, run_alignment_check

ALIGNMENT_RESPONSES = [
    '{"status": "partial", "findings": [{"requirement_id": "S1", "issue": "No error shown on bad password", "recommendation": "Add inline error text"}]}',
    '{"status": "aligned", "findings": []}',
]


def _fake_openai_client(responses):
    client = MagicMock()
    calls = iter(responses)

    def _create(**kwargs):
        content = next(calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=700, completion_tokens=180),
        )

    client.chat.completions.create.side_effect = _create
    return client


@pytest.fixture
def approved_requirements_and_design_doc():
    with get_session() as s:
        project = Project(name="pytest-alignment-project")
        s.add(project)
        s.flush()

        req_doc = Document(
            project_id=project.id,
            doc_type="requirement",
            version=1,
            approval_status="approved",
            source_filename="requirements.pdf",
        )
        s.add(req_doc)
        s.flush()

        epic = RequirementItem(document_id=req_doc.id, type="epic", external_id="E1", text="Auth")
        s.add(epic)
        s.flush()
        story = RequirementItem(
            document_id=req_doc.id,
            type="story",
            external_id="S1",
            parent_id=epic.id,
            text="As a user, I can log in with email/password.",
            acceptance_criteria=["Shows an error on wrong password"],
        )
        s.add(story)
        s.flush()

        design_doc = Document(
            project_id=project.id,
            doc_type="design",
            version=1,
            approval_status="draft",
            source_filename="screens.pdf",
            checked_against_document_id=req_doc.id,
        )
        s.add(design_doc)
        s.flush()

        ids = (project.id, req_doc.id, design_doc.id)

    yield ids

    project_id, req_doc_id, design_doc_id = ids
    with get_session() as s:
        for row in s.query(AiCall).filter(AiCall.document_id == design_doc_id):
            s.delete(row)
        report_ids = [
            r.id for r in s.query(AlignmentReport).filter(AlignmentReport.design_document_id == design_doc_id)
        ]
        for row in s.query(AlignmentFinding).filter(AlignmentFinding.alignment_report_id.in_(report_ids)):
            s.delete(row)
    with get_session() as s:
        for row in s.query(AlignmentReport).filter(AlignmentReport.design_document_id == design_doc_id):
            s.delete(row)
    with get_session() as s:
        for row in s.query(RequirementItem).filter(
            RequirementItem.document_id == req_doc_id, RequirementItem.parent_id.isnot(None)
        ):
            s.delete(row)
    with get_session() as s:
        for row in s.query(RequirementItem).filter(RequirementItem.document_id == req_doc_id):
            s.delete(row)
    # design_doc references req_doc via checked_against_document_id, so it must
    # be deleted first (and in its own committed transaction — see the
    # SQLite FK-checking note in backend/tests/verify_schema.py).
    for doc_id in (design_doc_id, req_doc_id):
        with get_session() as s:
            d = s.query(Document).filter(Document.id == doc_id).first()
            if d:
                s.delete(d)
    with get_session() as s:
        p = s.query(Project).filter(Project.id == project_id).first()
        if p:
            s.delete(p)


def test_get_approved_stories(approved_requirements_and_design_doc):
    _project_id, req_doc_id, _design_doc_id = approved_requirements_and_design_doc
    with get_session() as s:
        stories = get_approved_stories(s, req_doc_id)
    assert len(stories) == 1
    assert stories[0].external_id == "S1"
    assert stories[0].acceptance_criteria == ["Shows an error on wrong password"]


def test_run_alignment_check_persists_reports_findings_and_ai_calls(
    monkeypatch, approved_requirements_and_design_doc
):
    project_id, req_doc_id, design_doc_id = approved_requirements_and_design_doc
    client = _fake_openai_client(ALIGNMENT_RESPONSES)

    fake_screens = [(1, Image.new("RGB", (10, 10))), (2, Image.new("RGB", (10, 10)))]
    monkeypatch.setattr("app.services.design_alignment._load_screens", lambda doc_id: fake_screens)

    with get_session() as s:
        design_doc = s.query(Document).filter(Document.id == design_doc_id).first()
        req_doc = s.query(Document).filter(Document.id == req_doc_id).first()
        run_alignment_check(s, design_doc, req_doc, client, model="gpt-4o")

    with get_session() as s:
        reports = (
            s.query(AlignmentReport)
            .filter(AlignmentReport.design_document_id == design_doc_id)
            .order_by(AlignmentReport.page)
            .all()
        )
        assert len(reports) == 2
        assert reports[0].page == 1
        assert reports[0].status == "partial"
        assert reports[1].page == 2
        assert reports[1].status == "aligned"

        findings_page1 = (
            s.query(AlignmentFinding).filter(AlignmentFinding.alignment_report_id == reports[0].id).all()
        )
        assert len(findings_page1) == 1
        assert findings_page1[0].issue == "No error shown on bad password"
        # requirement_id "S1" correctly resolved to the real RequirementItem FK
        story = s.query(RequirementItem).filter(
            RequirementItem.document_id == req_doc_id, RequirementItem.external_id == "S1"
        ).first()
        assert findings_page1[0].requirement_item_id == story.id

        findings_page2 = (
            s.query(AlignmentFinding).filter(AlignmentFinding.alignment_report_id == reports[1].id).all()
        )
        assert len(findings_page2) == 0

        calls = s.query(AiCall).filter(AiCall.document_id == design_doc_id).all()
        assert len(calls) == 2
        assert all(c.call_type == "alignment" for c in calls)
