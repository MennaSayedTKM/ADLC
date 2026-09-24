"""
End-to-end HTTP-level test of the design review API: upload+approve
requirements, then upload a design screen checked against that approved
version, view alignment findings, resolve one, and fetch the screen image.
OpenAI (both requirements extraction and design alignment currently go
through it — see config.yaml's extraction_model) and the embedding server
are both mocked.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai.embed_client import EmbedClient
from ai.ingest.ingest import META_PATH, tiles_for_document
from app.db.models import Document, Project
from app.db.session import get_session
from app.deps import get_embed_client, get_openai_client
from app.main import app

EXTRACTION_DATA = {
    "epics": [{"id": "E1", "title": "User Authentication", "assumptions": [], "dependencies": []}],
    "user_stories": [
        {
            "id": "S1",
            "epic_id": "E1",
            "title": "Log in with email/password",
            "description": "As a user, I can log in with email/password.",
            "scenarios": [],
            "acceptance_criteria": [{"text": "Shows an error on wrong password", "out_of_scope": False}],
            "error_handling": [],
        }
    ],
    "gaps": [],
}


def _fake_extraction_client():
    def factory():
        client = MagicMock()

        def create(**kwargs):
            tool_choice = kwargs.get("tool_choice")
            requested_name = tool_choice["function"]["name"] if tool_choice else "record_extraction"
            if requested_name == "record_granularity_audit":
                tool_input = {
                    "epic_findings": [
                        {"epic_id": e["id"], "under_split": False, "missing_capabilities": []}
                        for e in EXTRACTION_DATA["epics"]
                    ]
                }
            else:
                tool_input = EXTRACTION_DATA
            tool_call = SimpleNamespace(
                function=SimpleNamespace(name=requested_name, arguments=json.dumps(tool_input))
            )
            # content is set too (not just tool_calls) — the extraction pipeline's
            # coverage-audit call is a plain-text completion, not a tool call.
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content="(no coverage findings)"))],
                usage=SimpleNamespace(prompt_tokens=500, completion_tokens=150),
            )

        client.chat.completions.create.side_effect = create
        return client

    return factory


ALIGNMENT_JSON = (
    '{"status": "partial", "findings": '
    '[{"requirement_id": "S1", "issue": "No inline error state in the mockup", '
    '"recommendation": "Add a red error message below the password field", '
    '"bounding_box": {"top": 40, "left": 10, "bottom": 55, "right": 90}}]}'
)


def _fake_openai_client(content: str):
    """
    Returns a factory (not a client) — get_openai_client is a FastAPI
    dependency, resolved fresh per request, so each call site below swaps in
    the response it needs right before making that request rather than
    sharing one iterator across requests.
    """
    def factory():
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=500, completion_tokens=150),
        )
        return client

    return factory


def _fake_embed_image(self, image):
    rng = np.random.default_rng(1)
    v = rng.random(16).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def client():
    app.dependency_overrides[get_embed_client] = lambda: EmbedClient(
        base_url="http://fake-embed-server.invalid"
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_files(tmp_path):
    req_path = tmp_path / "requirements.pdf"
    c = canvas.Canvas(str(req_path))
    c.drawString(72, 720, "Epic 1: User Authentication")
    c.drawString(72, 700, "Users can log in with email and password.")
    c.save()

    screen_path = tmp_path / "login_screen.png"
    screen = Image.new("RGB", (900, 1200), color="white")
    ImageDraw.Draw(screen).text((40, 40), "Login screen mockup", fill="black")
    screen.save(screen_path)

    return req_path, screen_path


def test_design_review_flow(client, sample_files):
    req_path, screen_path = sample_files
    project_id = None
    doc_ids = []

    try:
        r = client.post("/projects", json={"name": "pytest-design-flow-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        app.dependency_overrides[get_openai_client] = _fake_extraction_client()
        with open(req_path, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        req_doc_id = r.json()["document"]["id"]
        doc_ids.append(req_doc_id)

        # can't upload a design yet — nothing approved (fails before any OpenAI call)
        with patch.object(EmbedClient, "embed_image", _fake_embed_image):
            with open(screen_path, "rb") as f:
                r = client.post(
                    f"/projects/{project_id}/designs",
                    files={"file": ("login_screen.png", f, "image/png")},
                )
        assert r.status_code == 409, r.text

        r = client.post(f"/projects/{project_id}/requirements/{req_doc_id}/approve")
        assert r.status_code == 200, r.text

        # now the design upload should succeed, checked against the approved version
        app.dependency_overrides[get_openai_client] = _fake_openai_client(ALIGNMENT_JSON)
        with patch.object(EmbedClient, "embed_image", _fake_embed_image):
            with open(screen_path, "rb") as f:
                r = client.post(
                    f"/projects/{project_id}/designs",
                    files={"file": ("login_screen.png", f, "image/png")},
                )
        assert r.status_code == 201, r.text
        body = r.json()
        design_doc_id = body["document"]["id"]
        doc_ids.append(design_doc_id)
        assert body["pages_indexed"] == 1
        assert body["screens_checked"] == 1
        assert body["partial_count"] == 1

        # GET the latest design (no doc_id) should return the same thing
        r = client.get(f"/projects/{project_id}/designs")
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["document"]["id"] == design_doc_id
        assert detail["requirements_document_id"] == req_doc_id
        assert len(detail["reports"]) == 1
        report = detail["reports"][0]
        assert report["status"] == "partial"
        assert len(report["findings"]) == 1
        finding = report["findings"][0]
        assert finding["requirement_external_id"] == "S1"
        assert finding["resolution_status"] == "open"
        assert finding["bounding_box"] == {"top": 40.0, "left": 10.0, "bottom": 55.0, "right": 90.0}

        # GET by explicit doc_id matches
        r = client.get(f"/projects/{project_id}/designs/{design_doc_id}/alignment")
        assert r.status_code == 200, r.text
        assert r.json()["document"]["id"] == design_doc_id

        # resolve the finding
        r = client.patch(
            f"/projects/{project_id}/designs/{design_doc_id}/findings/{finding['id']}",
            json={"status": "resolved"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["reports"][0]["findings"][0]["resolution_status"] == "resolved"

        # fetch the screen image
        r = client.get(f"/projects/{project_id}/designs/{design_doc_id}/screens/1/image")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/png"
        assert len(r.content) > 0

        # nonexistent page 404s cleanly
        r = client.get(f"/projects/{project_id}/designs/{design_doc_id}/screens/99/image")
        assert r.status_code == 404

    finally:
        _cleanup(project_id, doc_ids)


def _cleanup(project_id, document_ids):
    from app.db.models import AiCall, AlignmentFinding, AlignmentReport, Gap, RequirementItem

    if not project_id:
        return

    tile_paths = []
    for doc_id in document_ids:
        tile_paths += [t["tile_path"] for t in tiles_for_document(doc_id)]

    # Deleted level by level, children before parents — AlignmentFinding
    # references both AlignmentReport and RequirementItem, so it goes first,
    # same for every other level down to Document.
    with get_session() as s:
        for doc_id in document_ids:
            for row in s.query(AiCall).filter(AiCall.document_id == doc_id):
                s.delete(row)

    with get_session() as s:
        for doc_id in document_ids:
            report_ids = [
                r.id for r in s.query(AlignmentReport).filter(AlignmentReport.design_document_id == doc_id)
            ]
            if report_ids:
                for row in s.query(AlignmentFinding).filter(
                    AlignmentFinding.alignment_report_id.in_(report_ids)
                ):
                    s.delete(row)

    with get_session() as s:
        for doc_id in document_ids:
            for row in s.query(AlignmentReport).filter(AlignmentReport.design_document_id == doc_id):
                s.delete(row)
            for row in s.query(Gap).filter(Gap.document_id == doc_id):
                s.delete(row)

    with get_session() as s:
        for doc_id in document_ids:
            for row in s.query(RequirementItem).filter(
                RequirementItem.document_id == doc_id, RequirementItem.parent_id.isnot(None)
            ):
                s.delete(row)

    with get_session() as s:
        for doc_id in document_ids:
            for row in s.query(RequirementItem).filter(RequirementItem.document_id == doc_id):
                s.delete(row)

    # design doc (references the requirements doc via checked_against_document_id)
    # must be deleted before the requirements doc, each its own transaction.
    with get_session() as s:
        docs_by_id = {
            d.id: d.checked_against_document_id
            for d in s.query(Document).filter(Document.id.in_(document_ids)).all()
        }
    ordered_ids = sorted(document_ids, key=lambda did: docs_by_id.get(did) is None)
    for doc_id in ordered_ids:
        with get_session() as s:
            d = s.query(Document).filter(Document.id == doc_id).first()
            if d:
                s.delete(d)

    with get_session() as s:
        p = s.query(Project).filter(Project.id == project_id).first()
        if p:
            s.delete(p)

    for tp in tile_paths:
        Path(tp).unlink(missing_ok=True)

    if META_PATH.exists():
        meta = json.loads(META_PATH.read_text())
        meta = [m for m in meta if m.get("document_id") not in document_ids]
        META_PATH.write_text(json.dumps(meta, indent=2))
