"""
deps.py
Shared FastAPI dependencies for external clients — same pattern as the
original api.py's _get_client(), extended with an OpenAI client getter
(design alignment, and requirements extraction — see config.yaml's
extraction_model). get_anthropic_client() is unused for now (requirements
extraction runs on OpenAI temporarily); kept so switching back is a one-line
config change, not a re-setup.
"""

import os
import sys
from pathlib import Path

from fastapi import HTTPException

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.embed_client import EmbedClient  # noqa: E402

from .services.confluence_client import ConfluenceClient


def get_confluence_client() -> ConfluenceClient:
    base_url = os.environ.get("CONFLUENCE_BASE_URL", "")
    email = os.environ.get("CONFLUENCE_EMAIL", "")
    token = os.environ.get("CONFLUENCE_API_TOKEN", "")
    space_key = os.environ.get("CONFLUENCE_SPACE_KEY", "")
    if not all([base_url, email, token, space_key]):
        raise HTTPException(
            status_code=503,
            detail="Confluence is not configured — set CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, "
            "CONFLUENCE_API_TOKEN, and CONFLUENCE_SPACE_KEY in .env",
        )
    return ConfluenceClient(base_url=base_url, email=email, api_token=token, space_key=space_key)


def get_embed_client() -> EmbedClient:
    url = os.environ.get("EMBED_API_URL", "")
    if not url:
        raise HTTPException(status_code=503, detail="EMBED_API_URL is not set in .env")
    return EmbedClient(base_url=url)


def get_openai_client():
    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not set in .env")
    return OpenAI(api_key=key)


def get_anthropic_client():
    from anthropic import Anthropic

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not set in .env")
    return Anthropic(api_key=key)
