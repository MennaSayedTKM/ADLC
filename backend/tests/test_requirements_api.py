"""
End-to-end HTTP-level test of the requirements review API, via FastAPI's
TestClient. OpenAI is mocked (no live API spend needed) — everything else
(FastAPI routing, request validation, SQLite persistence, version-forking on
edit-after-approval, gap resolution) is real.
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

from app.db.models import AiCall, Document, Gap, Project, RequirementItem
from app.db.session import get_session
from app.deps import get_confluence_client, get_openai_client
from app.main import app
from app.routers.requirements import _join_suggestion_threads_for_tests
from app.services.confluence_client import ConfluenceError

VALID_EXTRACTION = {
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
    "gaps": [{"description": "No password reset flow mentioned", "location": "Section 1", "severity": "medium"}],
}


def _fake_openai_response(tool_input: dict, tool_name: str = "record_extraction"):
    tool_call = SimpleNamespace(
        function=SimpleNamespace(name=tool_name, arguments=json.dumps(tool_input))
    )
    # content is set too (not just tool_calls) — the extraction pipeline's
    # coverage-audit call is a plain-text completion, not a tool call, and
    # reads .content; the same fake response serves all pipeline calls.
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content="(no coverage findings)"))],
        usage=SimpleNamespace(prompt_tokens=400, completion_tokens=120),
    )


def _fake_openai_client():
    client = MagicMock()

    def create(**kwargs):
        tool_choice = kwargs.get("tool_choice")
        requested_name = tool_choice["function"]["name"] if tool_choice else "record_extraction"
        if requested_name == "record_granularity_audit":
            findings = {
                "epic_findings": [
                    {"epic_id": e["id"], "under_split": False, "missing_capabilities": []}
                    for e in VALID_EXTRACTION["epics"]
                ]
            }
            return _fake_openai_response(findings, tool_name=requested_name)
        return _fake_openai_response(VALID_EXTRACTION, tool_name=requested_name)

    client.chat.completions.create.side_effect = create
    return client


@pytest.fixture
def client():
    app.dependency_overrides[get_openai_client] = _fake_openai_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_requirements_pdf(tmp_path):
    p = tmp_path / "requirements.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(72, 720, "Epic 1: User Authentication")
    c.drawString(72, 700, "Users can log in with email and password.")
    c.save()
    return p


def test_full_requirements_review_flow(client, sample_requirements_pdf):
    created_document_ids = []
    project_id = None

    try:
        # 1. create a project
        r = client.post("/projects", json={"name": "pytest-api-flow-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        # 2. upload + extract
        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        body = r.json()
        doc_v1_id = body["document"]["id"]
        created_document_ids.append(doc_v1_id)
        assert body["document"]["version"] == 1
        assert body["document"]["approval_status"] == "draft"
        assert body["epics_extracted"] == 1
        assert body["stories_extracted"] == 1
        assert body["gaps_found"] == 1

        # 3. GET latest requirements — should match what we just uploaded
        r = client.get(f"/projects/{project_id}/requirements")
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["document"]["id"] == doc_v1_id
        assert len(detail["epics"]) == 1
        assert len(detail["stories"]) == 1
        epic_id = detail["epics"][0]["id"]
        story_id = detail["stories"][0]["id"]
        gap_id = detail["gaps"][0]["id"]
        assert detail["unresolved_gap_count"] == 1

        # 4. edit the story while still draft — mutates in place, same doc id
        r = client.patch(
            f"/projects/{project_id}/requirements/{doc_v1_id}/items/{story_id}",
            json={"text": "Log in with email/password or SSO"},
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["document"]["id"] == doc_v1_id  # no fork — still draft
        assert "SSO" in detail["stories"][0]["text"]

        # 5. resolve the gap into a new story under the existing epic
        r = client.post(
            f"/projects/{project_id}/requirements/{doc_v1_id}/gaps/{gap_id}/resolve-as-story",
            json={"parent_id": epic_id},
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["unresolved_gap_count"] == 0
        assert detail["gaps"][0]["status"] == "resolved"
        assert len(detail["stories"]) == 2
        new_story = next(s for s in detail["stories"] if s["id"] != story_id)
        assert new_story["text"] == "No password reset flow mentioned"

        # 6. approve
        r = client.post(f"/projects/{project_id}/requirements/{doc_v1_id}/approve")
        assert r.status_code == 200, r.text
        assert r.json()["approval_status"] == "approved"

        # 7. approving again should fail (already approved)
        r = client.post(f"/projects/{project_id}/requirements/{doc_v1_id}/approve")
        assert r.status_code == 409

        # 8. editing an item on the now-approved doc forks a new version
        r = client.patch(
            f"/projects/{project_id}/requirements/{doc_v1_id}/items/{story_id}",
            json={"text": "Log in with email/password, SSO, or a magic link"},
        )
        assert r.status_code == 200, r.text
        forked = r.json()
        assert forked["document"]["id"] != doc_v1_id
        assert forked["document"]["version"] == 2
        assert forked["document"]["approval_status"] == "draft"
        assert forked["document"]["previous_version_id"] == doc_v1_id
        edited_story = next(s for s in forked["stories"] if "magic link" in s["text"])
        assert edited_story is not None
        # both stories (original edit + gap-resolved) carried forward
        assert len(forked["stories"]) == 2
        assert forked["unresolved_gap_count"] == 0
        created_document_ids.append(forked["document"]["id"])

        # 9. the original approved version is untouched
        r = client.get(f"/projects/{project_id}/requirements/{doc_v1_id}")
        assert r.status_code == 200, r.text
        untouched_texts = [s["text"] for s in r.json()["stories"]]
        assert "SSO" in untouched_texts[0] or "SSO" in untouched_texts[1]
        assert not any("magic link" in t for t in untouched_texts)

    finally:
        _cleanup(project_id, created_document_ids)


def test_gap_dismiss_and_reopen(client, sample_requirements_pdf):
    """The 'ignore' resolution path — PATCH .../gaps/{gap_id}. 'resolved' isn't
    settable directly here; that's what resolve-as-story is for."""
    project_id = None
    created_document_ids = []

    try:
        r = client.post("/projects", json={"name": "pytest-gap-dismiss-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)

        detail = client.get(f"/projects/{project_id}/requirements").json()
        gap_id = detail["gaps"][0]["id"]
        assert detail["unresolved_gap_count"] == 1

        # 'resolved' can't be set directly — must go through resolve-as-story
        r = client.patch(
            f"/projects/{project_id}/requirements/{doc_id}/gaps/{gap_id}",
            json={"status": "resolved"},
        )
        assert r.status_code == 400, r.text
        assert "resolve-as-story" in r.json()["detail"]

        # dismiss
        r = client.patch(
            f"/projects/{project_id}/requirements/{doc_id}/gaps/{gap_id}",
            json={"status": "dismissed"},
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["gaps"][0]["status"] == "dismissed"
        assert detail["unresolved_gap_count"] == 0
        assert len(detail["stories"]) == 1  # dismissing never creates an item

        # reopen
        r = client.patch(
            f"/projects/{project_id}/requirements/{doc_id}/gaps/{gap_id}",
            json={"status": "open"},
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["gaps"][0]["status"] == "open"
        assert detail["unresolved_gap_count"] == 1

    finally:
        _cleanup(project_id, created_document_ids)


def test_resolve_gap_as_story_with_ai_generated_draft(client, sample_requirements_pdf):
    """The generate-draft endpoint (seeded with the gap's own description)
    plus resolve-as-story carrying the full draft, mirrors the standalone
    'Add with AI' flow instead of leaving a bare-title story."""
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-ai-gap-resolve-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)

        detail = client.get(f"/projects/{project_id}/requirements").json()
        epic_id = detail["epics"][0]["id"]
        gap_id = detail["gaps"][0]["id"]

        story_draft = {
            "title": "Support password reset",
            "description": "As a user, I want to reset my password, so that I can regain access.",
            "scenarios": [
                {"title": "Request reset", "given": "I forgot my password", "when": "I request a reset", "then": "I receive an email", "source_reference": ""}
            ],
            "acceptance_criteria": [{"text": "A reset email is sent on request", "out_of_scope": False}],
            "error_handling": [],
        }
        app.dependency_overrides[get_openai_client] = lambda: MagicMock(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(
                            tool_calls=[SimpleNamespace(function=SimpleNamespace(
                                name="record_story_draft", arguments=json.dumps(story_draft),
                            ))],
                            content="",
                        ))],
                        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20),
                    )
                )
            )
        )

        r = client.post(
            f"/projects/{project_id}/requirements/{doc_id}/items/generate-draft",
            json={"kind": "story", "subject": detail["gaps"][0]["description"], "parent_id": epic_id},
        )
        assert r.status_code == 200, r.text
        draft = r.json()

        r = client.post(
            f"/projects/{project_id}/requirements/{doc_id}/gaps/{gap_id}/resolve-as-story",
            json={
                "parent_id": epic_id,
                "text": draft["title"],
                "description": draft["description"],
                "scenarios": draft["scenarios"],
                "acceptance_criteria": draft["acceptance_criteria"],
                "error_handling": draft["error_handling"],
                "origin": "pm_ai_assisted",
            },
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        new_story = next(s for s in detail["stories"] if s["text"] == "Support password reset")
        assert new_story["origin"] == "pm_ai_assisted"
        assert len(new_story["scenarios"]) == 1
        assert len(new_story["acceptance_criteria"]) == 1
        assert detail["gaps"][0]["status"] == "resolved"
        assert detail["gaps"][0]["resolved_as_item_id"] == new_story["id"]
    finally:
        _cleanup(project_id, created_document_ids)


def test_resolve_gap_as_story_on_approved_document_forks_new_version(client, sample_requirements_pdf):
    """Resolving a gap on an already-approved document forks a new version
    (same rule as edit_item/create_item) — the fork must land the new story
    AND the gap's resolved state on the same forked copy, and leave the
    original approved document's gap untouched."""
    project_id = None
    created_document_ids = []

    try:
        r = client.post("/projects", json={"name": "pytest-gap-fork-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)

        detail = client.get(f"/projects/{project_id}/requirements").json()
        epic_id = detail["epics"][0]["id"]
        gap_id = detail["gaps"][0]["id"]

        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
        assert r.status_code == 200, r.text

        r = client.post(
            f"/projects/{project_id}/requirements/{doc_id}/gaps/{gap_id}/resolve-as-story",
            json={"parent_id": epic_id},
        )
        assert r.status_code == 200, r.text
        forked = r.json()
        forked_doc_id = forked["document"]["id"]
        assert forked_doc_id != doc_id
        assert forked["document"]["version"] == 2
        assert forked["document"]["approval_status"] == "draft"
        assert forked["document"]["previous_version_id"] == doc_id
        assert forked["unresolved_gap_count"] == 0

        forked_gap = forked["gaps"][0]
        assert forked_gap["status"] == "resolved"
        assert forked_gap["resolved_as_item_id"] is not None

        assert len(forked["stories"]) == 2
        new_story = next(s for s in forked["stories"] if s["id"] == forked_gap["resolved_as_item_id"])
        assert new_story["text"] == "No password reset flow mentioned"
        # the new story attached under the *forked* epic, not the original
        assert new_story["parent_id"] == forked["epics"][0]["id"]
        assert forked["epics"][0]["id"] != epic_id
        created_document_ids.append(forked_doc_id)

        # the original approved version is untouched — gap still open, no new story
        r = client.get(f"/projects/{project_id}/requirements/{doc_id}")
        assert r.status_code == 200, r.text
        original = r.json()
        assert original["gaps"][0]["status"] == "open"
        assert original["gaps"][0]["resolved_as_item_id"] is None
        assert len(original["stories"]) == 1

    finally:
        _cleanup(project_id, created_document_ids)


def test_change_request_extraction_merges_into_new_approved_baseline_version(client, sample_requirements_pdf):
    """A CR filed against an approved requirements version forks a new draft
    version from that baseline instead of living as a disconnected document."""
    created_document_ids = []
    project_id = None

    try:
        r = client.post("/projects", json={"name": "pytest-cr-flow-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        doc_v1_id = r.json()["document"]["id"]
        created_document_ids.append(doc_v1_id)
        _join_suggestion_threads_for_tests()  # let this upload's own suggestion (if any) settle first

        r = client.post(f"/projects/{project_id}/requirements/{doc_v1_id}/approve")
        assert r.status_code == 200, r.text

        cr_extraction = {
            "epics": [],
            "user_stories": [
                {
                    "id": "S9",
                    "epic_id": "E1",
                    "title": "Log in with a magic link",
                    "description": "As a user, I can log in via a magic link sent to my email.",
                    "scenarios": [],
                    "acceptance_criteria": [{"text": "Link expires after 15 minutes", "out_of_scope": False}],
                    "error_handling": [],
                }
            ],
            "gaps": [],
        }
        def cr_create(**kwargs):
            tool_choice = kwargs.get("tool_choice")
            requested_name = tool_choice["function"]["name"] if tool_choice else "record_extraction"
            if requested_name == "record_granularity_audit":
                findings = {
                    "epic_findings": [
                        {"epic_id": e["id"], "under_split": False, "missing_capabilities": []}
                        for e in cr_extraction.get("epics", [])
                    ]
                }
                return _fake_openai_response(findings, tool_name=requested_name)
            return _fake_openai_response(cr_extraction)

        app.dependency_overrides[get_openai_client] = lambda: MagicMock(
            chat=SimpleNamespace(completions=SimpleNamespace(create=cr_create))
        )

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements/change-requests",
                files={"file": ("cr.pdf", f, "application/pdf")},
                data={"request_type": "Enhancement", "classification": "Minor"},
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["change_request_document"]["doc_type"] == "change_request"
        assert body["change_request_document"]["type_metadata"]["request_type"] == "Enhancement"
        assert body["change_request_document"]["type_metadata"]["classification"] == "Minor"
        new_version = body["requirements_document"]
        assert new_version["id"] != doc_v1_id
        assert new_version["version"] == 2
        assert new_version["previous_version_id"] == doc_v1_id
        assert new_version["type_metadata"]["source_change_request_id"] == body["change_request_document"]["id"]
        assert body["stories_extracted"] == 1
        created_document_ids.append(new_version["id"])
        created_document_ids.append(body["change_request_document"]["id"])

        r = client.get(f"/projects/{project_id}/requirements/{new_version['id']}")
        assert r.status_code == 200, r.text
        detail = r.json()
        assert len(detail["epics"]) == 1  # baseline epic carried forward, not duplicated
        assert len(detail["stories"]) == 2  # original story + the CR's new one
        magic_link_story = next(s for s in detail["stories"] if "magic link" in s["text"])
        assert magic_link_story["parent_id"] == detail["epics"][0]["id"]
        # The CR proposed "S9" for this story (see cr_extraction above), but the
        # baseline document doesn't actually have 8 other stories — it must
        # land as a real next-sequential id, not the LLM's own out-of-context
        # one. Confirmed directly: this was the cause of newly-added items
        # showing up as e.g. "S23" and sorting above the existing ones
        # (string-sorted "S23" precedes "S9" too). Not asserting the exact
        # number here (a pending AI-suggestion story from the same upload's
        # automatic suggestions step can legitimately occupy a slot first,
        # since it's a real persisted row even while hidden from this view)
        # — what matters is it's NOT the LLM's arbitrary "S9", and the
        # response is in strict ascending numeric order.
        assert magic_link_story["external_id"] != "S9"
        story_nums = [int(s["external_id"][1:]) for s in detail["stories"]]
        assert story_nums == sorted(story_nums)

    finally:
        _cleanup(project_id, created_document_ids)


def test_epics_returned_in_numeric_order_past_double_digits(client, sample_requirements_pdf):
    """A naive query with no explicit ORDER BY was being satisfied via the
    (document_id, external_id) unique index, sorting external_id as a
    STRING — so a document with ten-plus epics would show "E10" between
    "E1" and "E2" instead of at the end. Confirmed directly against a real
    project. Manually adding epics past E9 is the simplest way to force a
    double-digit id and prove the fix is a real numeric sort, not just
    incidentally correct for single digits."""
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-numeric-order-project"})
        project_id = r.json()["id"]
        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)
        _join_suggestion_threads_for_tests()  # let this upload's own suggestion (if any) settle first

        # Baseline has E1 already (from VALID_EXTRACTION) — add nine more so a
        # double-digit id actually gets exercised. Not asserting a perfectly
        # gap-free E1..E10 sequence — the same upload's automatic suggestions
        # step can legitimately place a pending (hidden) suggestion epic in
        # between, consuming a real slot even while invisible here — what
        # matters is strict ascending numeric order and reaching two digits.
        for i in range(9):
            r = client.post(
                f"/projects/{project_id}/requirements/{doc_id}/items",
                json={"type": "epic", "text": f"Manually added epic {i}"},
            )
            assert r.status_code == 201, r.text

        detail = client.get(f"/projects/{project_id}/requirements/{doc_id}").json()
        external_nums = [int(e["external_id"][1:]) for e in detail["epics"]]
        assert external_nums == sorted(external_nums)
        assert len(external_nums) == 10
        assert external_nums[-1] >= 10

    finally:
        _cleanup(project_id, created_document_ids)


def test_change_request_rejects_invalid_request_type(client, sample_requirements_pdf):
    """request_type is constrained to the nCubex CR template's own fixed set
    (New Feature / Enhancement / Configuration / Report / Integration /
    Business Support) — anything else should be rejected before an LLM call
    is ever made, not silently stored as free text."""
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-cr-invalid-type-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)

        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
        assert r.status_code == 200, r.text

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements/change-requests",
                files={"file": ("cr.pdf", f, "application/pdf")},
                data={"request_type": "Not A Real Type"},
            )
        assert r.status_code == 422, r.text

    finally:
        _cleanup(project_id, created_document_ids)


SUGGESTION_EXTRACTION = {
    "epics": [],
    "user_stories": [
        {
            "id": "S1",  # collides with the real extraction's own S1 — exercises the rename path
            "epic_id": "E1",
            "title": "Reset password via emailed link",
            "description": "As a user, I want to reset my password via an emailed link, so that I can "
            "regain access if I forget it.",
            "scenarios": [],
            "acceptance_criteria": [{"text": "A password reset email is sent when requested", "out_of_scope": False}],
            "error_handling": [],
        }
    ],
    "gaps": [],
}


def _client_with_suggestions(main_input: dict, suggestion_input: dict):
    """
    The main extraction pipeline (draft/audit/review) always declares its
    own epics — echoing that same content back for the suggestions call
    too (like the plain _fake_openai_client does) makes generate_suggestions
    see its own epic as a duplicate and fail validation, which
    _run_suggestions then silently swallows (by design — suggestions are
    advisory, never allowed to break the real upload). That's invisible to
    tests that don't check the suggestions list, but these do, so they need
    a fake that returns a genuinely different (collision-free) payload once
    the main 3-call pipeline is done.
    """
    call_count = {"n": 0}

    def create(**kwargs):
        call_count["n"] += 1
        tool_choice = kwargs.get("tool_choice")
        requested_name = tool_choice["function"]["name"] if tool_choice else "record_extraction"
        if requested_name == "record_granularity_audit":
            # The main pipeline's own granularity audit (4th call) — report
            # everything already correctly split so its conditional repair
            # call never fires and doesn't consume another position in the
            # call_count sequence the suggestions call below relies on.
            findings = {
                "epic_findings": [
                    {"epic_id": e["id"], "under_split": False, "missing_capabilities": []}
                    for e in main_input.get("epics", [])
                ]
            }
            return _fake_openai_response(findings, tool_name=requested_name)
        return _fake_openai_response(main_input if call_count["n"] <= 3 else suggestion_input)

    return MagicMock(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_suggestions_appear_hidden_and_can_be_accepted(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        app.dependency_overrides[get_openai_client] = lambda: _client_with_suggestions(
            VALID_EXTRACTION, SUGGESTION_EXTRACTION
        )

        r = client.post("/projects", json={"name": "pytest-suggestions-accept-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)
        _join_suggestion_threads_for_tests()  # suggestions now generate on a background thread

        detail = client.get(f"/projects/{project_id}/requirements").json()
        assert len(detail["stories"]) == 1  # the real extracted story only
        assert len(detail["suggestions"]) == 1
        suggestion = detail["suggestions"][0]
        assert suggestion["origin"] == "ai_suggestion"
        assert suggestion["suggestion_status"] == "pending"

        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/suggestions/{suggestion['id']}/accept")
        assert r.status_code == 200, r.text
        detail = r.json()
        assert len(detail["suggestions"]) == 0
        assert len(detail["stories"]) == 2
        accepted = next(s for s in detail["stories"] if s["id"] == suggestion["id"])
        assert accepted["suggestion_status"] == "accepted"
    finally:
        _cleanup(project_id, created_document_ids)


def test_suggestions_can_be_dismissed(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        app.dependency_overrides[get_openai_client] = lambda: _client_with_suggestions(
            VALID_EXTRACTION, SUGGESTION_EXTRACTION
        )

        r = client.post("/projects", json={"name": "pytest-suggestions-dismiss-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)
        _join_suggestion_threads_for_tests()  # suggestions now generate on a background thread

        detail = client.get(f"/projects/{project_id}/requirements").json()
        suggestion_id = detail["suggestions"][0]["id"]

        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/suggestions/{suggestion_id}/dismiss")
        assert r.status_code == 200, r.text
        detail = r.json()
        assert len(detail["suggestions"]) == 0
        assert len(detail["stories"]) == 1  # dismissed suggestion never enters the real tree

        # accepting/dismissing again should 404 — it's no longer pending
        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/suggestions/{suggestion_id}/accept")
        assert r.status_code == 404
    finally:
        _cleanup(project_id, created_document_ids)


def test_ai_assisted_item_generation_and_confirm(client, sample_requirements_pdf):
    """POST .../items/generate-draft returns a draft without persisting
    anything; confirming it goes through the existing create-item endpoint
    with origin="pm_ai_assisted" so it's clearly labeled apart from
    extracted content."""
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-ai-assisted-add-project"})
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        assert r.status_code == 201, r.text
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)
        epic_id = client.get(f"/projects/{project_id}/requirements").json()["epics"][0]["id"]

        story_draft = {
            "title": "Test drafted story",
            "description": "As a user, I want this, so that that.",
            "scenarios": [],
            "acceptance_criteria": [{"text": "It works", "out_of_scope": False}],
            "error_handling": [],
        }
        app.dependency_overrides[get_openai_client] = lambda: MagicMock(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(
                            tool_calls=[SimpleNamespace(function=SimpleNamespace(
                                name="record_story_draft", arguments=json.dumps(story_draft),
                            ))],
                            content="",
                        ))],
                        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20),
                    )
                )
            )
        )

        r = client.post(
            f"/projects/{project_id}/requirements/{doc_id}/items/generate-draft",
            json={"kind": "story", "subject": "a test story", "parent_id": epic_id},
        )
        assert r.status_code == 200, r.text
        draft = r.json()
        assert draft["title"] == "Test drafted story"

        r = client.post(
            f"/projects/{project_id}/requirements/{doc_id}/items",
            json={
                "type": "story",
                "parent_id": epic_id,
                "text": draft["title"],
                "description": draft["description"],
                "scenarios": draft["scenarios"],
                "acceptance_criteria": draft["acceptance_criteria"],
                "error_handling": draft["error_handling"],
                "origin": "pm_ai_assisted",
            },
        )
        assert r.status_code == 201, r.text
        detail = r.json()
        added = next(s for s in detail["stories"] if s["text"] == "Test drafted story")
        assert added["origin"] == "pm_ai_assisted"
    finally:
        _cleanup(project_id, created_document_ids)


def test_delete_story(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-delete-story-project"})
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)

        detail = client.get(f"/projects/{project_id}/requirements").json()
        story_id = detail["stories"][0]["id"]

        r = client.delete(f"/projects/{project_id}/requirements/{doc_id}/items/{story_id}")
        assert r.status_code == 200, r.text
        detail = r.json()
        assert len(detail["stories"]) == 0
        assert len(detail["epics"]) == 1  # the epic itself is untouched
    finally:
        _cleanup(project_id, created_document_ids)


def test_delete_epic_cascades_its_stories(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-delete-epic-project"})
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)

        detail = client.get(f"/projects/{project_id}/requirements").json()
        epic_id = detail["epics"][0]["id"]
        assert len(detail["stories"]) == 1  # sanity check on the fixture

        r = client.delete(f"/projects/{project_id}/requirements/{doc_id}/items/{epic_id}")
        assert r.status_code == 200, r.text
        detail = r.json()
        assert len(detail["epics"]) == 0
        assert len(detail["stories"]) == 0  # cascaded away with its epic
    finally:
        _cleanup(project_id, created_document_ids)


def test_delete_story_reverts_the_gap_it_was_resolved_from(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-delete-reverts-gap-project"})
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)

        detail = client.get(f"/projects/{project_id}/requirements").json()
        epic_id = detail["epics"][0]["id"]
        gap_id = detail["gaps"][0]["id"]

        r = client.post(
            f"/projects/{project_id}/requirements/{doc_id}/gaps/{gap_id}/resolve-as-story",
            json={"parent_id": epic_id},
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["gaps"][0]["status"] == "resolved"
        resolved_story = next(s for s in detail["stories"] if s["id"] == detail["gaps"][0]["resolved_as_item_id"])

        r = client.delete(f"/projects/{project_id}/requirements/{doc_id}/items/{resolved_story['id']}")
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["gaps"][0]["status"] == "open"
        assert detail["gaps"][0]["resolved_as_item_id"] is None
    finally:
        _cleanup(project_id, created_document_ids)


def test_delete_on_approved_document_forks_new_version(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-delete-approved-project"})
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_v1_id = r.json()["document"]["id"]
        created_document_ids.append(doc_v1_id)

        r = client.post(f"/projects/{project_id}/requirements/{doc_v1_id}/approve")
        assert r.status_code == 200, r.text

        detail = client.get(f"/projects/{project_id}/requirements/{doc_v1_id}").json()
        story_id = detail["stories"][0]["id"]

        r = client.delete(f"/projects/{project_id}/requirements/{doc_v1_id}/items/{story_id}")
        assert r.status_code == 200, r.text
        forked = r.json()
        assert forked["document"]["id"] != doc_v1_id
        assert forked["document"]["version"] == 2
        assert len(forked["stories"]) == 0
        created_document_ids.append(forked["document"]["id"])

        # the original approved version is untouched
        r = client.get(f"/projects/{project_id}/requirements/{doc_v1_id}")
        assert len(r.json()["stories"]) == 1
    finally:
        _cleanup(project_id, created_document_ids)


def test_generate_draft_scenario_and_error_handling_kinds(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-draft-scenario-eh-project"})
        project_id = r.json()["id"]

        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)
        story_id = client.get(f"/projects/{project_id}/requirements").json()["stories"][0]["id"]

        scenario_draft = {"title": "It works", "given": "a", "when": "b", "then": "c"}
        app.dependency_overrides[get_openai_client] = lambda: MagicMock(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(
                            tool_calls=[SimpleNamespace(function=SimpleNamespace(
                                name="record_scenario_draft", arguments=json.dumps(scenario_draft),
                            ))],
                            content="",
                        ))],
                        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                    )
                )
            )
        )
        r = client.post(
            f"/projects/{project_id}/requirements/{doc_id}/items/generate-draft",
            json={"kind": "scenario", "subject": "it works", "parent_id": story_id},
        )
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "It works"
        assert r.json()["source_reference"] is None or r.json()["source_reference"] == ""

        eh_draft = {"condition": "bad input", "message": "[TBD: exact copy]"}
        app.dependency_overrides[get_openai_client] = lambda: MagicMock(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(
                            tool_calls=[SimpleNamespace(function=SimpleNamespace(
                                name="record_error_handling_draft", arguments=json.dumps(eh_draft),
                            ))],
                            content="",
                        ))],
                        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                    )
                )
            )
        )
        r = client.post(
            f"/projects/{project_id}/requirements/{doc_id}/items/generate-draft",
            json={"kind": "error_handling", "subject": "bad input", "parent_id": story_id},
        )
        assert r.status_code == 200, r.text
        assert r.json() == eh_draft
    finally:
        _cleanup(project_id, created_document_ids)


def _cleanup(project_id, document_ids):
    """
    Deletes in dependency order (children before parents) — all in a single
    transaction, which SQLite's real per-statement FK checking handles fine
    as long as the order is correct. Documents can point at each other two
    ways (previous_version_id, checked_against_document_id — a CR doc points
    at the baseline it was filed against), so documents are deleted by
    repeatedly removing whichever ones nothing else in the set still
    references, rather than assuming a single linear chain.

    Joins any pending suggestions threads (see _spawn_suggestions_thread)
    first — every upload in this file spawns one, so without this, a slow
    one can still be running (and holding the single-writer lock) when the
    next test's own request tries to acquire it, or could try to write
    after this very cleanup already deleted its target document.
    """
    _join_suggestion_threads_for_tests()
    if not project_id:
        return

    with get_session() as s:
        for doc_id in document_ids:
            s.query(AiCall).filter(AiCall.document_id == doc_id).delete()
            s.query(Gap).filter(Gap.document_id == doc_id).delete()
            s.query(RequirementItem).filter(
                RequirementItem.document_id == doc_id, RequirementItem.parent_id.isnot(None)
            ).delete()
            s.query(RequirementItem).filter(RequirementItem.document_id == doc_id).delete()

        # SQLAlchemy batches same-table deletes from one flush into a single
        # executemany call, ignoring python call order — so each delete here
        # is flushed individually, otherwise two documents that reference
        # each other can end up in the same batch and violate the FK either way.
        remaining = {d.id: d for d in s.query(Document).filter(Document.id.in_(document_ids)).all()}
        while remaining:
            referenced_ids = {d.previous_version_id for d in remaining.values() if d.previous_version_id}
            referenced_ids |= {d.checked_against_document_id for d in remaining.values() if d.checked_against_document_id}
            deletable = [d for d in remaining.values() if d.id not in referenced_ids] or list(remaining.values())
            for d in deletable:
                s.delete(d)
                s.flush()
                del remaining[d.id]

        p = s.query(Project).filter(Project.id == project_id).first()
        if p:
            s.delete(p)


# --- POST /{doc_id}/publish-confluence ---

class FakeConfluenceClient:
    """In-memory stand-in matching ConfluenceClient's interface exactly, so
    confluence_export.py's logic (index-page caching, parent linkage,
    bidirectional supersede banners) runs unmodified against it."""

    def __init__(self):
        self.pages: dict[str, dict] = {}
        self._next_id = 1000

    def find_page_by_title(self, title):
        return next((p for p in self.pages.values() if p["title"] == title), None)

    def create_page(self, title, body_html, parent_id=None):
        if self.find_page_by_title(title) is not None:  # real Confluence rejects duplicate titles per space
            raise ConfluenceError(400, "A page with this title already exists")
        page_id = str(self._next_id)
        self._next_id += 1
        page = {
            "id": page_id,
            "title": title,
            "body": {"storage": {"value": body_html}},
            "version": {"number": 1},
            "parent_id": parent_id,
            "_links": {"webui": f"/pages/{page_id}"},
        }
        self.pages[page_id] = page
        return page

    def get_page(self, page_id):
        return self.pages[page_id]

    def update_page(self, page_id, title, body_html, next_version):
        page = self.pages[page_id]
        page["title"] = title
        page["body"]["storage"]["value"] = body_html
        page["version"]["number"] = next_version
        return page

    def page_url(self, page):
        return f"https://fake.atlassian.net/wiki{page['_links']['webui']}"


def test_publish_confluence_requires_approved_version(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-confluence-not-approved-project"})
        project_id = r.json()["id"]
        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)

        app.dependency_overrides[get_confluence_client] = lambda: FakeConfluenceClient()
        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/publish-confluence")
        assert r.status_code == 400, r.text
    finally:
        _cleanup(project_id, created_document_ids)


def test_publish_confluence_creates_index_and_version_page(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-confluence-publish-project"})
        project_id = r.json()["id"]
        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)
        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
        assert r.status_code == 200, r.text

        fake = FakeConfluenceClient()
        app.dependency_overrides[get_confluence_client] = lambda: fake

        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/publish-confluence")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["page_url"].startswith("https://fake.atlassian.net/wiki/pages/")

        # one index page + one version page, version page parented under the index
        assert len(fake.pages) == 2
        version_page = fake.pages[body["page_id"]]
        index_page_id = version_page["parent_id"]
        assert index_page_id is not None
        assert fake.pages[index_page_id]["parent_id"] is None

        # the published page is the stakeholder-facing business document
        assert "Business Requirements v1" in version_page["title"]
        page_body = version_page["body"]["storage"]["value"]
        assert "BR-1.1" in page_body
        assert "Stakeholder Sign-off" in page_body
        assert "<strong>Given</strong>" not in page_body

        # persisted on the document, and republishing reuses it without creating another page
        r = client.get(f"/projects/{project_id}/requirements/{doc_id}")
        assert r.json()["document"]["type_metadata"]["confluence"]["page_id"] == body["page_id"]

        r2 = client.post(f"/projects/{project_id}/requirements/{doc_id}/publish-confluence")
        assert r2.status_code == 200, r2.text
        assert r2.json()["page_id"] == body["page_id"]
        assert len(fake.pages) == 2  # no new page created on the second call

    finally:
        _cleanup(project_id, created_document_ids)


def test_publish_confluence_links_new_version_to_superseded_one(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-confluence-supersede-project"})
        project_id = r.json()["id"]
        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        v1_id = r.json()["document"]["id"]
        created_document_ids.append(v1_id)
        r = client.post(f"/projects/{project_id}/requirements/{v1_id}/approve")
        assert r.status_code == 200, r.text

        fake = FakeConfluenceClient()
        app.dependency_overrides[get_confluence_client] = lambda: fake

        r = client.post(f"/projects/{project_id}/requirements/{v1_id}/publish-confluence")
        v1_page_id = r.json()["page_id"]

        # Editing after approval forks a new draft version (v2); approve and publish it too.
        detail = client.get(f"/projects/{project_id}/requirements/{v1_id}").json()
        epic_id = detail["epics"][0]["id"]
        r = client.patch(
            f"/projects/{project_id}/requirements/{v1_id}/items/{epic_id}",
            json={"text": "Edited epic title"},
        )
        assert r.status_code == 200, r.text
        v2_id = r.json()["document"]["id"]
        assert v2_id != v1_id
        created_document_ids.append(v2_id)

        r = client.post(f"/projects/{project_id}/requirements/{v2_id}/approve")
        assert r.status_code == 200, r.text
        r = client.post(f"/projects/{project_id}/requirements/{v2_id}/publish-confluence")
        assert r.status_code == 200, r.text
        v2_page_id = r.json()["page_id"]

        assert v2_page_id != v1_page_id
        assert "superseded" in fake.pages[v1_page_id]["body"]["storage"]["value"].lower()
        assert "supersedes" in fake.pages[v2_page_id]["body"]["storage"]["value"].lower()
        # both version pages share the same index page parent
        assert fake.pages[v1_page_id]["parent_id"] == fake.pages[v2_page_id]["parent_id"]

    finally:
        _cleanup(project_id, created_document_ids)


def test_publish_confluence_reuses_pages_published_from_another_environment(client, sample_requirements_pdf):
    """The same project was already published from another TKMiND instance
    (e.g. a laptop before the AWS deployment): its index page is adopted,
    and the old version page is left untouched while the new one gets a
    numbered title — Confluence rejects duplicate titles in a space."""
    from datetime import datetime, timezone

    from app.services.business_document import format_date

    name = "pytest-confluence-existing-project"
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": name})
        project_id = r.json()["id"]
        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)
        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
        assert r.status_code == 200, r.text

        fake = FakeConfluenceClient()
        old_index = fake.create_page(f"{name} — Requirements", "<p>old index</p>")
        version_title = f"{name} — Business Requirements v1 (Approved {format_date(datetime.now(timezone.utc))})"
        old_version = fake.create_page(version_title, "<p>old version</p>", parent_id=old_index["id"])
        app.dependency_overrides[get_confluence_client] = lambda: fake

        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/publish-confluence")
        assert r.status_code == 200, r.text

        new_page = fake.pages[r.json()["page_id"]]
        assert new_page["parent_id"] == old_index["id"]  # existing index page adopted, not duplicated
        assert new_page["title"] == f"{version_title} (2)"
        assert fake.pages[old_version["id"]]["body"]["storage"]["value"] == "<p>old version</p>"
        assert len(fake.pages) == 3

    finally:
        _cleanup(project_id, created_document_ids)


def test_publish_confluence_surfaces_api_error_as_502(client, sample_requirements_pdf):
    project_id = None
    created_document_ids = []
    try:
        r = client.post("/projects", json={"name": "pytest-confluence-error-project"})
        project_id = r.json()["id"]
        with open(sample_requirements_pdf, "rb") as f:
            r = client.post(
                f"/projects/{project_id}/requirements",
                files={"file": ("requirements.pdf", f, "application/pdf")},
            )
        doc_id = r.json()["document"]["id"]
        created_document_ids.append(doc_id)
        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/approve")
        assert r.status_code == 200, r.text

        class FailingConfluenceClient(FakeConfluenceClient):
            def create_page(self, title, body_html, parent_id=None):
                raise ConfluenceError(403, "permission denied")

        app.dependency_overrides[get_confluence_client] = lambda: FailingConfluenceClient()
        r = client.post(f"/projects/{project_id}/requirements/{doc_id}/publish-confluence")
        assert r.status_code == 502, r.text
        assert "permission denied" in r.text

    finally:
        _cleanup(project_id, created_document_ids)
