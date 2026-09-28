"""
Tests for serve.py — the container's single-process entry point: API under
/api (prefix stripped, same contract as the Vite dev proxy) and the built
frontend at /.
"""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def serve_client(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html><body>TKMiND</body></html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ok')")
    monkeypatch.setenv("TKMIND_FRONTEND_DIST", str(tmp_path))

    import app.serve as serve

    serve = importlib.reload(serve)  # re-read TKMIND_FRONTEND_DIST
    with TestClient(serve.app) as c:
        yield c


def test_api_is_served_under_api_prefix(serve_client):
    r = serve_client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert serve_client.get("/api/projects").status_code == 200


def test_frontend_is_served_at_root(serve_client):
    r = serve_client.get("/")
    assert r.status_code == 200
    assert "TKMiND" in r.text
    assert serve_client.get("/assets/app.js").status_code == 200


def test_api_docs_stay_available_under_api(serve_client):
    assert serve_client.get("/api/docs").status_code == 200
