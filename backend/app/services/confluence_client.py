"""
confluence_client.py
Thin wrapper around the Confluence Cloud REST API (v1, /wiki/rest/api) —
just the handful of operations the publish-to-Confluence feature needs:
create a page, fetch one (for its current version number/body), and update
one. No caching, no retry logic beyond what `requests` gives for free —
this is a low-volume, PM-triggered action, not a hot path.
"""

from typing import Any, Optional

import requests


class ConfluenceError(Exception):
    """Raised on any non-2xx response from the Confluence API, with the
    response body attached so the caller can surface something actionable
    rather than a bare status code."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Confluence API error {status_code}: {detail}")


class ConfluenceClient:
    def __init__(self, base_url: str, email: str, api_token: str, space_key: str):
        self.base_url = base_url.rstrip("/")
        self.space_key = space_key
        self._auth = (email, api_token)

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        response = requests.request(
            method,
            f"{self.base_url}/rest/api{path}",
            auth=self._auth,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
            **kwargs,
        )
        if not response.ok:
            raise ConfluenceError(response.status_code, response.text[:1000])
        return response.json() if response.content else {}

    def get_page(self, page_id: str) -> dict[str, Any]:
        """Current title/body/version — version.number is required to PUT an update."""
        return self._request(
            "GET", f"/content/{page_id}", params={"expand": "body.storage,version"}
        )

    def find_page_by_title(self, title: str) -> Optional[dict[str, Any]]:
        """The page in this space with exactly this title, or None — Confluence
        titles are unique per space, so creating a duplicate fails with 400."""
        results = self._request(
            "GET",
            "/content",
            params={"spaceKey": self.space_key, "title": title, "type": "page", "expand": "version"},
        ).get("results", [])
        return results[0] if results else None

    def create_page(self, title: str, body_html: str, parent_id: Optional[str] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": self.space_key},
            "body": {"storage": {"value": body_html, "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        return self._request("POST", "/content", json=payload)

    def update_page(self, page_id: str, title: str, body_html: str, next_version: int) -> dict[str, Any]:
        payload = {
            "type": "page",
            "title": title,
            "version": {"number": next_version},
            "body": {"storage": {"value": body_html, "representation": "storage"}},
        }
        return self._request("PUT", f"/content/{page_id}", json=payload)

    def page_url(self, page: dict[str, Any]) -> str:
        webui = page.get("_links", {}).get("webui", "")
        return f"{self.base_url}{webui}" if webui else self.base_url
