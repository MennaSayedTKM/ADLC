"""
bedrock_embed_client.py
Embedding client backed by Cohere Embed v4 on Amazon Bedrock — a managed,
pay-per-call replacement for the self-hosted Qwen3-VL embedding server
(ai/embed_client.py + embed_server/), so no GPU has to run.

Same public interface as EmbedClient (embed_image / embed_text / health)
and the same failure type (EmbedServerError), so ingest_file() and the
routers use either one unchanged. Which one the app uses is chosen by
`embed_provider` in config.yaml.

Vectors from this client live in a different space (and dimension) from
Qwen3-VL's: an index built with one provider can't be extended with the
other — ingest_file() refuses to mix them.

Credentials come from the standard AWS chain: the instance role on AWS, or
`AWS_PROFILE=adlc` (+ `aws sso login --profile adlc`) for local development.
"""

import base64
import io
import json
from typing import List, Optional, Union

import numpy as np
from PIL import Image

from ai.embed_client import EmbedServerError

# Keep request bodies comfortably under Bedrock's payload limit; a 1344px
# PNG tile is normally well below this, JPEG is only a fallback.
_MAX_IMAGE_BYTES = 4 * 1024 * 1024


class BedrockEmbedClient:
    def __init__(
        self,
        model_id: str,
        region: str,
        dimension: int,
        bedrock_runtime=None,
    ):
        self.model_id = model_id
        self.region = region
        self.dimension = dimension
        if bedrock_runtime is None:
            import boto3
            from botocore.config import Config

            bedrock_runtime = boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=Config(retries={"max_attempts": 3, "mode": "standard"}, read_timeout=60),
            )
        self._runtime = bedrock_runtime
        self._usage = {"image_tokens": 0, "text_tokens": 0, "calls": 0}

    # ------------------------------------------------------------------
    # Public API (mirrors EmbedClient)
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """No network call — Bedrock is a managed service with nothing to warm up."""
        return {"status": "ok", "provider": "bedrock", "model": self.model_id}

    def embed_image(self, image: Union[Image.Image, bytes]) -> List[float]:
        """Embed a page/screen image for retrieval (input_type=search_document)."""
        return self._invoke(
            {"input_type": "search_document", "images": [self._image_to_data_uri(image)]},
            usage_key="image_tokens",
        )

    def embed_text(self, text: str) -> List[float]:
        """Embed a text query in the same space as images (input_type=search_query)."""
        if not text.strip():
            raise ValueError("text must not be empty")
        return self._invoke({"input_type": "search_query", "texts": [text]}, usage_key="text_tokens")

    def pop_usage(self) -> dict:
        """Token counts accumulated since the last call, then reset — the
        caller logs them to ai_calls against the right document."""
        usage, self._usage = self._usage, {"image_tokens": 0, "text_tokens": 0, "calls": 0}
        return usage

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _invoke(self, body: dict, usage_key: str) -> List[float]:
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

        body = {**body, "embedding_types": ["float"], "output_dimension": self.dimension}
        try:
            response = self._runtime.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            payload = json.loads(response["body"].read())
        except NoCredentialsError as e:
            raise EmbedServerError(
                "No AWS credentials for Bedrock. Locally: run `aws sso login --profile adlc` "
                "and set AWS_PROFILE=adlc in .env."
            ) from e
        except ClientError as e:
            err = e.response.get("Error", {})
            raise EmbedServerError(
                f"Bedrock embedding call failed ({err.get('Code', 'error')}): {err.get('Message', e)}"
            ) from e
        except BotoCoreError as e:
            raise EmbedServerError(f"Bedrock embedding call failed: {e}") from e

        try:
            vector = payload["embeddings"]["float"][0]
        except (KeyError, IndexError, TypeError) as e:
            raise EmbedServerError(f"Unexpected Bedrock embedding response: {str(payload)[:300]}") from e

        headers = response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
        self._usage[usage_key] += int(headers.get("x-amzn-bedrock-input-token-count", 0) or 0)
        self._usage["calls"] += 1

        # Unit-normalise so FAISS inner product == cosine similarity, the
        # same convention as the Qwen3-VL server's pooled vectors.
        vec = np.asarray(vector, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        return (vec / norm).tolist() if norm else vec.tolist()

    def _image_to_data_uri(self, image: Union[Image.Image, bytes]) -> str:
        if isinstance(image, bytes):
            image = Image.open(io.BytesIO(image))
        if not isinstance(image, Image.Image):
            raise TypeError(f"Expected PIL.Image or bytes, got {type(image)}")
        image = image.convert("RGB")

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        mime = "image/png"
        if buf.tell() > _MAX_IMAGE_BYTES:
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=90)
            mime = "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"


def estimate_cost_usd(usage: dict, image_cost_per_million: float, text_cost_per_million: float) -> float:
    return (
        usage.get("image_tokens", 0) * image_cost_per_million
        + usage.get("text_tokens", 0) * text_cost_per_million
    ) / 1_000_000


def make_client_from_config(bedrock_runtime: Optional[object] = None) -> BedrockEmbedClient:
    from config import BEDROCK_EMBED_MODEL, BEDROCK_REGION, EMBED_DIMENSION

    return BedrockEmbedClient(
        model_id=BEDROCK_EMBED_MODEL,
        region=BEDROCK_REGION,
        dimension=EMBED_DIMENSION,
        bedrock_runtime=bedrock_runtime,
    )
