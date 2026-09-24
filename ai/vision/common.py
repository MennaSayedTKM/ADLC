"""
common.py
Shared helpers for the GPT-4o vision modules (extraction, alignment, and the
ported rerank/answer logic) — factored out of PixelRAG's answer.py so every
vision module builds image payloads the same way.
"""

import base64
import io

from PIL import Image


def image_to_data_url(img: Image.Image, detail: str = "high") -> dict:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64}", "detail": detail},
    }


def parse_json_object(raw: str) -> dict:
    """
    Extract the first {...} JSON object from a model response. GPT-4o is
    instructed to return only JSON, but this tolerates stray commentary or
    markdown fences around it, matching the brace-scanning approach already
    used by the ported answer.py reranker.
    """
    import json

    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Model did not return a JSON object: {raw[:200]!r}")
    return json.loads(raw[start:end + 1])
