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
import threading
from datetime import datetime, timedelta, timezone
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


def get_jira_client():
    """Jira on the same Atlassian site and account as Confluence: the site is
    CONFLUENCE_BASE_URL without /wiki unless JIRA_BASE_URL says otherwise, and
    JIRA_EMAIL / JIRA_API_TOKEN override the Confluence account if set."""
    from config import JIRA_REQUEST_TIMEOUT_SECONDS

    from .services.jira_client import JiraClient

    confluence = os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/")
    base_url = os.environ.get("JIRA_BASE_URL") or (confluence[: -len("/wiki")] if confluence.endswith("/wiki") else confluence)
    email = os.environ.get("JIRA_EMAIL") or os.environ.get("CONFLUENCE_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN") or os.environ.get("CONFLUENCE_API_TOKEN", "")
    if not all([base_url, email, token]):
        raise HTTPException(
            status_code=503,
            detail="Jira is not configured — it uses the Confluence settings (CONFLUENCE_BASE_URL, "
            "CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN) or JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN.",
        )
    return JiraClient(base_url=base_url, email=email, api_token=token, timeout_seconds=JIRA_REQUEST_TIMEOUT_SECONDS)


def get_embed_client():
    """EmbedClient (self-hosted Qwen3-VL server) or BedrockEmbedClient
    (Cohere Embed v4) — same interface, chosen by config.yaml's embed_provider."""
    from config import EMBED_PROVIDER

    if EMBED_PROVIDER == "bedrock":
        from ai.bedrock_embed_client import make_client_from_config

        return make_client_from_config()
    if EMBED_PROVIDER != "http":
        raise HTTPException(status_code=503, detail=f"Unknown embed_provider {EMBED_PROVIDER!r} in config.yaml")

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


def get_optional_openai_client():
    """The OpenAI client, or None when no key is configured — for features
    that degrade gracefully (use-case diagrams fall back to a plain drawing)."""
    try:
        return get_openai_client()
    except HTTPException:
        return None


_role_credentials: dict | None = None
_role_credentials_lock = threading.Lock()


def _coding_role_credentials(role_arn: str, region: str) -> dict:
    """Short-lived credentials for coding_prompt_role_arn, reused until five
    minutes before they expire (an assumed role lasts an hour)."""
    global _role_credentials
    with _role_credentials_lock:
        cached = _role_credentials
        if (
            cached is None
            or cached["role_arn"] != role_arn
            or cached["expires"] - datetime.now(timezone.utc) < timedelta(minutes=5)
        ):
            import boto3

            sts = boto3.client("sts", region_name=region)
            issued = sts.assume_role(RoleArn=role_arn, RoleSessionName="adlc-coding-prompt")["Credentials"]
            cached = {
                "role_arn": role_arn,
                "access_key": issued["AccessKeyId"],
                "secret_key": issued["SecretAccessKey"],
                "session_token": issued["SessionToken"],
                "expires": issued["Expiration"],
            }
            _role_credentials = cached
        return cached


def get_coding_llm_client():
    """Claude on Amazon Bedrock (EU region) for coding prompts — the Anthropic
    SDK's Bedrock client on the standard bedrock-runtime endpoint (InvokeModel).
    Not the newer Messages-API endpoint (AnthropicBedrockMantle): that one
    answered "model does not exist" for every Claude model, even in an account
    where the console playground runs them (2026-10-18). It uses the AWS
    credentials the app already has (the ECS task role in production,
    AWS_PROFILE locally), or, when coding_prompt_role_arn is set, that role in
    the other AWS account."""
    from anthropic import AnthropicBedrock
    from botocore.exceptions import BotoCoreError, ClientError

    from config import CODING_PROMPT_REGION, CODING_PROMPT_ROLE_ARN

    if not CODING_PROMPT_ROLE_ARN:
        return AnthropicBedrock(aws_region=CODING_PROMPT_REGION)
    try:
        creds = _coding_role_credentials(CODING_PROMPT_ROLE_ARN, CODING_PROMPT_REGION)
    except (BotoCoreError, ClientError) as e:
        raise HTTPException(
            status_code=502,
            detail=f"The coding model could not be reached: the Bedrock role in the other AWS account couldn't be used ({e}).",
        )
    return AnthropicBedrock(
        aws_region=CODING_PROMPT_REGION,
        aws_access_key=creds["access_key"],
        aws_secret_key=creds["secret_key"],
        aws_session_token=creds["session_token"],
    )


def get_anthropic_client():
    from anthropic import Anthropic

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not set in .env")
    return Anthropic(api_key=key)
