"""
Tests for manually adding epics/stories the extraction missed
(POST /projects/{project_id}/requirements/{doc_id}/items).
"""
import pytest
from fastapi.testclient import TestClient

from app.db.models import Document, Project
from app.db.session import get_session
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def draft_project():
    with get_session() as s:
        project = Project(name="pytest-create-item-project")
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
        ids = (project.id, doc.id)

    yield ids

    _cleanup(*ids)


def _cleanup(project_id, *document_ids):
    from app.db.models import AiCall, Gap, RequirementItem

    with get_session() as s:
        for doc_id in document_ids:
            for row in s.query(AiCall).filter(AiCall.document_id == doc_id):
                s.delete(row)
            for row in s.query(Gap).filter(Gap.document_id == doc_id):
                s.delete(row)
            for row in s.query(RequirementItem).filter(
                RequirementItem.document_id == doc_id, RequirementItem.parent_id.isnot(None)
            ):
                s.delete(row)
    with get_session() as s:
        for doc_id in document_ids:
            for row in s.query(RequirementItem).filter(RequirementItem.document_id == doc_id):
                s.delete(row)
    with get_session() as s:
        docs_by_id = {
            d.id: d.previous_version_id
            for d in s.query(Document).filter(Document.id.in_(document_ids)).all()
        }
    for doc_id in sorted(document_ids, key=lambda did: docs_by_id.get(did) is None):
        with get_session() as s:
            d = s.query(Document).filter(Document.id == doc_id).first()
            if d:
                s.delete(d)
    with get_session() as s:
        p = s.query(Project).filter(Project.id == project_id).first()
        if p:
            s.delete(p)


def test_create_epic_then_story_with_autoincrementing_ids(client, draft_project):
    project_id, doc_id = draft_project

    r = client.post(
        f"/projects/{project_id}/requirements/{doc_id}/items",
        json={"type": "epic", "text": "Manually added epic"},
    )
    assert r.status_code == 201, r.text
    detail = r.json()
    assert detail["document"]["id"] == doc_id  # draft — no fork
    assert len(detail["epics"]) == 1
    epic = detail["epics"][0]
    assert epic["external_id"] == "E1"
    assert epic["text"] == "Manually added epic"

    r = client.post(
        f"/projects/{project_id}/requirements/{doc_id}/items",
        json={
            "type": "story",
            "text": "Manually added story",
            "parent_id": epic["id"],
            "acceptance_criteria": [{"text": "Does the thing", "out_of_scope": False}],
        },
    )
    assert r.status_code == 201, r.text
    detail = r.json()
    assert len(detail["stories"]) == 1
    story = detail["stories"][0]
    assert story["external_id"] == "S1"
    assert story["parent_id"] == epic["id"]
    assert story["acceptance_criteria"] == [{"text": "Does the thing", "out_of_scope": False}]

    # a second epic gets E2, not colliding with E1
    r = client.post(
        f"/projects/{project_id}/requirements/{doc_id}/items",
        json={"type": "epic", "text": "Second epic"},
    )
    assert r.status_code == 201, r.text
    epics = r.json()["epics"]
    assert sorted(e["external_id"] for e in epics) == ["E1", "E2"]


def test_story_without_parent_id_rejected(client, draft_project):
    project_id, doc_id = draft_project
    r = client.post(
        f"/projects/{project_id}/requirements/{doc_id}/items",
        json={"type": "story", "text": "Orphan story"},
    )
    assert r.status_code == 400
    assert "parent_id" in r.json()["detail"]


def test_invalid_item_type_rejected(client, draft_project):
    project_id, doc_id = draft_project
    r = client.post(
        f"/projects/{project_id}/requirements/{doc_id}/items",
        json={"type": "task", "text": "Not a valid type"},
    )
    assert r.status_code == 400


def test_create_item_on_approved_document_forks_new_version(client, draft_project):
    project_id, doc_id = draft_project

    r = client.post(
        f"/projects/{project_id}/requirements/{doc_id}/items",
        json={"type": "epic", "text": "Epic before approval"},
    )
    assert r.status_code == 201, r.text
    epic_id = r.json()["epics"][0]["id"]

    r = client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
    assert r.status_code == 200, r.text

    r = client.post(
        f"/projects/{project_id}/requirements/{doc_id}/items",
        json={"type": "story", "text": "Story added after approval", "parent_id": epic_id},
    )
    assert r.status_code == 201, r.text
    detail = r.json()
    forked_doc_id = detail["document"]["id"]
    assert forked_doc_id != doc_id
    assert detail["document"]["version"] == 2
    assert detail["document"]["approval_status"] == "draft"
    assert detail["document"]["previous_version_id"] == doc_id
    # the epic was carried forward into the fork, and the new story correctly
    # points at the *forked* epic row, not the original
    assert len(detail["epics"]) == 1
    forked_epic_id = detail["epics"][0]["id"]
    assert forked_epic_id != epic_id
    assert detail["stories"][0]["parent_id"] == forked_epic_id

    # the original approved version is untouched
    r = client.get(f"/projects/{project_id}/requirements/{doc_id}")
    assert len(r.json()["stories"]) == 0

    _cleanup(project_id, doc_id, forked_doc_id)
