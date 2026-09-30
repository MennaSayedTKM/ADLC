"""Unit tests for the Cognito pre sign-up Lambda (infra/lambdas/pre_signup.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

import pre_signup  # noqa: E402


def _event(email, source="PreSignUp_SignUp"):
    return {"triggerSource": source, "request": {"userAttributes": {"email": email} if email is not None else {}}, "response": {}}


@pytest.fixture(autouse=True)
def allowed(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "tkmind.net")


@pytest.mark.parametrize("source", ["PreSignUp_SignUp", "PreSignUp_ExternalProvider", "PreSignUp_AdminCreateUser"])
def test_company_email_is_allowed_for_every_sign_up_path(source):
    event = _event("Menna.Sayed@TKMIND.net", source)
    assert pre_signup.handler(event, None) is event
    assert "autoConfirmUser" not in event["response"]  # self sign-ups still confirm by email code


@pytest.mark.parametrize(
    "email",
    [
        "someone@gmail.com",
        "attacker@tkmind.net.evil.com",
        "attacker@evil-tkmind.net",
        "a@b@tkmind.net",
        "no-at-sign",
        "",
        None,
    ],
)
def test_other_emails_are_refused(email):
    with pytest.raises(Exception, match="limited to @tkmind.net"):
        pre_signup.handler(_event(email), None)


def test_several_domains_can_be_allowed(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", "tkmind.net, @partner.com")
    assert pre_signup.handler(_event("x@partner.com"), None)
    with pytest.raises(Exception, match="@partner.com, @tkmind.net"):
        pre_signup.handler(_event("x@other.com"), None)
