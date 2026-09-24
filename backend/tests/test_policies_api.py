"""
HTTP-level tests for the standing-policies API (Phase 3 of the Requirements
Intake Quality feature) — global, PM-managed defaults, not scoped to any
project. Draft generation is the one AI-backed endpoint here; everything
else is plain CRUD with no mocking needed.
"""
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.deps import get_openai_client
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _fake_policy_draft_client(title: str, policy_text: str):
    def factory():
        client = MagicMock()
        tool_call = SimpleNamespace(
            function=SimpleNamespace(
                name="record_policy_draft",
                arguments=json.dumps({"title": title, "policy_text": policy_text}),
            )
        )
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call], content=""))],
            usage=SimpleNamespace(prompt_tokens=150, completion_tokens=60),
        )
        return client

    return factory


def test_create_and_list_policy(client):
    title = f"Data retention default {uuid.uuid4().hex[:8]}"
    r = client.post("/policies", json={"title": title, "policy_text": "Retain records for 7 years."})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == title
    assert body["is_active"] is True
    policy_id = body["id"]

    r = client.get("/policies")
    assert r.status_code == 200, r.text
    ids = [p["id"] for p in r.json()]
    assert policy_id in ids


def test_edit_and_deactivate_policy(client):
    title = f"Accessibility default {uuid.uuid4().hex[:8]}"
    r = client.post("/policies", json={"title": title, "policy_text": "Meet WCAG 2.1 AA."})
    assert r.status_code == 201, r.text
    policy_id = r.json()["id"]

    r = client.patch(f"/policies/{policy_id}", json={"policy_text": "Meet WCAG 2.2 AA."})
    assert r.status_code == 200, r.text
    assert r.json()["policy_text"] == "Meet WCAG 2.2 AA."
    assert r.json()["title"] == title  # unchanged

    r = client.patch(f"/policies/{policy_id}", json={"is_active": False})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False


def test_edit_unknown_policy_404s(client):
    r = client.patch("/policies/does-not-exist", json={"is_active": False})
    assert r.status_code == 404, r.text


def test_generate_policy_draft_returns_title_and_text_without_persisting(client):
    app.dependency_overrides[get_openai_client] = _fake_policy_draft_client(
        "Session timeout", "User sessions expire after 30 minutes of inactivity, unless the client specifies otherwise."
    )
    r = client.post("/policies/generate-draft", json={"subject": "auto-logout after inactivity"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Session timeout"
    assert "30 minutes" in body["policy_text"]

    # advisory only — nothing was saved
    r = client.get("/policies")
    assert r.status_code == 200, r.text
    assert all(p["title"] != "Session timeout" for p in r.json())


def test_generate_policy_draft_then_confirm_saves_it(client):
    app.dependency_overrides[get_openai_client] = _fake_policy_draft_client(
        "Session timeout", "User sessions expire after 30 minutes of inactivity, unless the client specifies otherwise."
    )
    r = client.post("/policies/generate-draft", json={"subject": "auto-logout after inactivity"})
    assert r.status_code == 200, r.text
    draft = r.json()

    r = client.post("/policies", json=draft)
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Session timeout"
    assert r.json()["is_active"] is True
