"""
Cognito pre sign-up trigger for the ADLC user pool.

Every way of getting an account runs through here: self sign-up on the
login page, "Sign in with Microsoft" (first sign-in creates the account),
and admin-created users. Anyone whose email isn't at an allowed domain
(ALLOWED_EMAIL_DOMAINS, comma-separated) is refused — the app has no
per-user permissions, so every signed-in user can see all projects.

Deliberately does NOT auto-confirm self sign-ups: people still prove they
own the address with the emailed code.
"""

import os


def _allowed_domains() -> set[str]:
    return {d.strip().lower().lstrip("@") for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()}


def handler(event, context):
    email = (event.get("request", {}).get("userAttributes", {}).get("email") or "").strip().lower()
    domain = email.rsplit("@", 1)[1] if email.count("@") == 1 else ""
    allowed = _allowed_domains()
    if not domain or domain not in allowed:
        # Cognito shows this message on the login page.
        raise Exception(f"ADLC is limited to {', '.join('@' + d for d in sorted(allowed))} accounts.")
    return event
