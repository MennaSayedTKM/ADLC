"""
app_settings.py
Company-wide settings, stored in app_settings as key -> JSON value. For now one:
the default Jira project key, used by every project that hasn't been connected
to a Jira project of its own.
"""

import re
from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import AppSetting

JIRA_DEFAULT_PROJECT_KEY = "jira_default_project_key"
PROJECT_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,9}$")


def get_jira_default_project_key(session: Session) -> Optional[str]:
    row = session.get(AppSetting, JIRA_DEFAULT_PROJECT_KEY)
    return (row.value or None) if row else None


def set_jira_default_project_key(session: Session, key: str) -> Optional[str]:
    """Saves the default (upper-cased); an empty key clears it. The key's format is
    checked here; the project itself is checked against Jira when a project connects."""
    key = (key or "").strip().upper()
    if key and not PROJECT_KEY_PATTERN.match(key):
        raise ValueError("Enter the Jira project key, e.g. TK (letters and digits, starting with a letter).")
    row = session.get(AppSetting, JIRA_DEFAULT_PROJECT_KEY)
    if row is None:
        row = AppSetting(key=JIRA_DEFAULT_PROJECT_KEY)
        session.add(row)
    row.value = key or None
    session.flush()
    return row.value
