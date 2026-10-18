"""
jira_client.py
Thin wrapper around the Jira Cloud REST API (v3) — the handful of operations
sending development stories needs: read a project and its issue types, read
the create screen's fields (to find story points and required fields), create
and update an issue, and attach a file. Same Atlassian site and account as
Confluence. Low-volume and person-triggered, like Confluence publishing, so
no caching or retries beyond what `requests` gives.
"""

from typing import Any

import requests


class JiraError(Exception):
    """A non-2xx response from Jira, with its body so the caller can say
    something actionable rather than a bare status code."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Jira API error {status_code}: {detail}")


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str, timeout_seconds: float = 30):
        self.base_url = base_url.rstrip("/")
        self._auth = (email, api_token)
        self._timeout = timeout_seconds

    def browse_url(self, issue_key: str) -> str:
        return f"{self.base_url}/browse/{issue_key}"

    def _request(self, method: str, path: str, **kwargs) -> Any:
        headers = {"Accept": "application/json", **kwargs.pop("headers", {})}
        if "json" in kwargs:
            headers["Content-Type"] = "application/json"
        response = requests.request(
            method,
            f"{self.base_url}/rest/api/3{path}",
            auth=self._auth,
            headers=headers,
            timeout=self._timeout,
            **kwargs,
        )
        if not response.ok:
            raise JiraError(response.status_code, response.text[:1000])
        return response.json() if response.content else {}

    def get_project(self, project_key: str) -> dict[str, Any]:
        """id, key, name, style (classic = company-managed, next-gen = team-managed)
        and issueTypes (each with id, name, subtask, hierarchyLevel)."""
        return self._request("GET", f"/project/{project_key}")

    def create_fields(self, project_key: str, issue_type_id: str) -> list[dict[str, Any]]:
        """The fields on the create screen of one issue type: fieldId, name, required."""
        data = self._request(
            "GET", f"/issue/createmeta/{project_key}/issuetypes/{issue_type_id}", params={"maxResults": 200}
        )
        return data.get("fields") or data.get("values") or []

    def issue_exists(self, issue_key: str) -> bool:
        try:
            self._request("GET", f"/issue/{issue_key}", params={"fields": "summary"})
            return True
        except JiraError as e:
            if e.status_code == 404:
                return False
            raise

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        """{"id", "key", "self"} of the new issue."""
        return self._request("POST", "/issue", json={"fields": fields})

    def update_issue(self, issue_key: str, fields: dict[str, Any], update: dict[str, Any] | None = None) -> None:
        """fields replace values; update holds per-value operations (e.g. adding
        one label without dropping the ones people added in Jira)."""
        body: dict[str, Any] = {"fields": fields}
        if update:
            body["update"] = update
        self._request("PUT", f"/issue/{issue_key}", json=body)

    def add_attachment(self, issue_key: str, filename: str, content: bytes, media_type: str) -> dict[str, Any]:
        """The created attachment ({"id", "filename", ...}). Jira requires the
        no-check header on multipart uploads (its CSRF guard)."""
        created = self._request(
            "POST",
            f"/issue/{issue_key}/attachments",
            headers={"X-Atlassian-Token": "no-check"},
            files={"file": (filename, content, media_type)},
        )
        return created[0] if isinstance(created, list) and created else {}
