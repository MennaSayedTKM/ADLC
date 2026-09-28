"""
Tests for ai/bedrock_embed_client.py (Cohere Embed v4 on Bedrock) and the
embedding-usage logging in services/ingestion.py. The Bedrock runtime is a
fake — no AWS credentials or network needed.
"""

import base64
import io
import json

import numpy as np
import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from PIL import Image

import ai.ingest.ingest as ingest_module
from ai.bedrock_embed_client import BedrockEmbedClient, estimate_cost_usd
from ai.embed_client import EmbedServerError
from app.db.models import AiCall, Document, Project
from app.db.session import get_session
from app.services.ingestion import ingest_document


class FakeBedrockRuntime:
    """Records invoke_model calls and returns a canned Cohere-v4-shaped response."""

    def __init__(self, dim=8, tokens=1000, error=None):
        self.dim = dim
        self.tokens = tokens
        self.error = error
        self.calls = []

    def invoke_model(self, modelId, body, contentType, accept):
        self.calls.append({"modelId": modelId, "body": json.loads(body)})
        if self.error:
            raise self.error
        vector = [3.0] + [0.0] * (self.dim - 2) + [4.0]  # norm 5 → normalised to 0.6 / 0.8
        return {
            "body": io.BytesIO(json.dumps({"embeddings": {"float": [vector]}, "response_type": "embeddings_by_type"}).encode()),
            "ResponseMetadata": {"HTTPHeaders": {"x-amzn-bedrock-input-token-count": str(self.tokens)}},
        }


def _client(runtime, dim=8):
    return BedrockEmbedClient(model_id="eu.cohere.embed-v4:0", region="eu-central-1", dimension=dim, bedrock_runtime=runtime)


def test_embed_image_sends_png_data_uri_as_search_document_and_normalises():
    runtime = FakeBedrockRuntime()
    vec = _client(runtime).embed_image(Image.new("RGB", (40, 30), "white"))

    call = runtime.calls[0]
    assert call["modelId"] == "eu.cohere.embed-v4:0"
    body = call["body"]
    assert body["input_type"] == "search_document"
    assert body["embedding_types"] == ["float"]
    assert body["output_dimension"] == 8
    uri = body["images"][0]
    assert uri.startswith("data:image/png;base64,")
    assert Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).size == (40, 30)
    assert np.isclose(np.linalg.norm(vec), 1.0)
    assert np.isclose(vec[0], 0.6) and np.isclose(vec[-1], 0.8)


def test_embed_text_is_a_search_query_and_rejects_empty_text():
    runtime = FakeBedrockRuntime()
    client = _client(runtime)
    client.embed_text("login screen")
    assert runtime.calls[0]["body"]["input_type"] == "search_query"
    assert runtime.calls[0]["body"]["texts"] == ["login screen"]
    with pytest.raises(ValueError):
        client.embed_text("   ")


def test_usage_accumulates_per_kind_and_resets_on_pop():
    client = _client(FakeBedrockRuntime(tokens=700))
    client.embed_image(Image.new("RGB", (10, 10)))
    client.embed_image(Image.new("RGB", (10, 10)))
    client.embed_text("q")
    assert client.pop_usage() == {"image_tokens": 1400, "text_tokens": 700, "calls": 3}
    assert client.pop_usage() == {"image_tokens": 0, "text_tokens": 0, "calls": 0}
    assert estimate_cost_usd({"image_tokens": 1_000_000, "text_tokens": 500_000}, 0.47, 0.12) == pytest.approx(0.53)


def test_aws_errors_become_embed_server_errors():
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no model access"}}, "InvokeModel")
    with pytest.raises(EmbedServerError, match="AccessDeniedException"):
        _client(FakeBedrockRuntime(error=denied)).embed_text("q")
    with pytest.raises(EmbedServerError, match="aws sso login"):
        _client(FakeBedrockRuntime(error=NoCredentialsError())).embed_text("q")


@pytest.fixture
def isolated_index(tmp_path, monkeypatch):
    """ingest_file reads these module globals at call time — point them at a
    private directory so this test's 8-dim vectors never meet the shared
    test index the design-API tests build with 16-dim vectors."""
    (tmp_path / "tiles").mkdir()
    monkeypatch.setattr(ingest_module, "TILES_DIR", tmp_path / "tiles")
    monkeypatch.setattr(ingest_module, "INDEX_PATH", tmp_path / "index.faiss")
    monkeypatch.setattr(ingest_module, "META_PATH", tmp_path / "metadata.json")
    return tmp_path


def test_ingest_document_logs_one_embedding_ai_call(isolated_index):
    screen = isolated_index / "screen.png"
    Image.new("RGB", (64, 48), "white").save(screen)
    client = _client(FakeBedrockRuntime(tokens=1200))

    with get_session() as s:
        project = Project(name="pytest-bedrock-embedding-project")
        s.add(project)
        s.flush()
        doc, pages = ingest_document(s, project.id, "design", screen, "screen.png", client)
        s.flush()
        rows = s.query(AiCall).filter(AiCall.document_id == doc.id).all()
        ids = (project.id, doc.id)

        assert pages == 1
        assert len(rows) == 1
        assert rows[0].call_type == "embedding"
        assert rows[0].model == "eu.cohere.embed-v4:0"
        assert rows[0].input_tokens == 1200 and rows[0].output_tokens == 0
        assert float(rows[0].estimated_cost_usd) > 0

    with get_session() as s:
        s.query(AiCall).filter(AiCall.document_id == ids[1]).delete()
        s.query(Document).filter(Document.id == ids[1]).delete()
        s.query(Project).filter(Project.id == ids[0]).delete()


def test_ingest_refuses_to_mix_vector_sizes_from_different_providers(isolated_index):
    screen = isolated_index / "screen.png"
    Image.new("RGB", (32, 32), "white").save(screen)
    ingest_module.ingest_file(screen, _client(FakeBedrockRuntime(dim=8), dim=8))
    with pytest.raises(ValueError, match="different embedding provider"):
        ingest_module.ingest_file(screen, _client(FakeBedrockRuntime(dim=16), dim=16))
