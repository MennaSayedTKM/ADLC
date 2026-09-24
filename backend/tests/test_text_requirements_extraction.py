"""
Tests for ai/text/requirements_extractor.py (OpenAI function-calling output).
The OpenAI client is mocked throughout — no network calls, no real cost.
"""
import json
from types import SimpleNamespace

import pytest

from ai.text.requirements_extractor import (
    ExistingEpic,
    _call_llm,
    _looks_already_well_split,
    ensure_standing_policy_coverage,
    extract_change_request,
    extract_requirements,
    generate_clarifying_questions,
    generate_item_draft,
    generate_suggestions,
    review_advisory_artifacts,
    review_output_stories,
    review_source_material,
    validate_extraction,
)

VALID_FRESH_EXTRACTION = {
    "epics": [{"id": "E1", "title": "Strategy Hierarchy", "assumptions": [], "dependencies": []}],
    "user_stories": [
        {
            "id": "S1",
            "epic_id": "E1",
            "title": "Configure Enterprise Strategy Hierarchy",
            "description": "As the Strategy Execution Office, we want to configure the strategy hierarchy.",
            "scenarios": [],
            "acceptance_criteria": [
                {"text": "The strategy hierarchy is fully configured and approved.", "out_of_scope": False}
            ],
            "error_handling": [],
        }
    ],
    "gaps": [{"description": "Scorecard perspectives are not finalized.", "location": "Section 4.1.C", "severity": "medium"}],
}


def _fake_response(
    tool_input: dict,
    prompt_tokens=1000,
    completion_tokens=400,
    content="(no coverage findings)",
    tool_name="record_extraction",
):
    tool_call = SimpleNamespace(
        function=SimpleNamespace(name=tool_name, arguments=json.dumps(tool_input))
    )
    # Both tool_calls (for the structured-output calls) and content (for the
    # plain-text coverage audit call) are set on every fake response, so the
    # same fixture works regardless of which pipeline call reads it.
    message = SimpleNamespace(tool_calls=[tool_call], content=content)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _fake_client(tool_input: dict, prompt_tokens=1000, completion_tokens=400):
    """
    Serves every pipeline call (draft, coverage audit, review, and the
    granularity audit) from the same underlying tool_input — for the
    granularity audit specifically, it reports every epic as already
    correctly split (under_split: False) so the conditional repair call
    never fires and existing tests' expectations don't need to account for
    it too.
    """
    client = SimpleNamespace()

    def create(**kwargs):
        tool_choice = kwargs.get("tool_choice")
        requested_name = tool_choice["function"]["name"] if tool_choice else "record_extraction"
        if requested_name == "record_granularity_audit":
            findings = {
                "epic_findings": [
                    {"epic_id": e["id"], "under_split": False, "missing_capabilities": []}
                    for e in tool_input.get("epics", [])
                ]
            }
            return _fake_response(findings, prompt_tokens, completion_tokens, tool_name=requested_name)
        return _fake_response(tool_input, prompt_tokens, completion_tokens, tool_name=requested_name)

    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
    return client


# --- pure validation ---

def test_validate_extraction_accepts_well_formed_data():
    validate_extraction(VALID_FRESH_EXTRACTION)  # should not raise


def test_validate_extraction_rejects_story_with_unknown_epic():
    data = {
        "epics": [{"id": "E1", "title": "x"}],
        "user_stories": [{"id": "S1", "epic_id": "E999", "title": "x", "description": "x", "acceptance_criteria": []}],
        "gaps": [],
    }
    with pytest.raises(ValueError, match="unknown epic_id"):
        validate_extraction(data)


def test_validate_extraction_accepts_epic_id_from_existing_baseline():
    data = {
        "epics": [],
        "user_stories": [{"id": "S1", "epic_id": "E2", "title": "x", "description": "x", "acceptance_criteria": []}],
        "gaps": [],
    }
    validate_extraction(data, existing_epic_ids={"E2"})  # should not raise


def test_validate_extraction_rejects_malformed_scenario():
    data = {
        "epics": [{"id": "E1", "title": "x"}],
        "user_stories": [{
            "id": "S1", "epic_id": "E1", "title": "x", "description": "x",
            "acceptance_criteria": [],
            "scenarios": [{"title": "missing given/when/then"}],
        }],
        "gaps": [],
    }
    with pytest.raises(ValueError, match="malformed scenario"):
        validate_extraction(data)


def test_validate_extraction_rejects_ac_missing_out_of_scope_flag():
    data = {
        "epics": [{"id": "E1", "title": "x"}],
        "user_stories": [{
            "id": "S1", "epic_id": "E1", "title": "x", "description": "x",
            "acceptance_criteria": [{"text": "x"}],
        }],
        "gaps": [],
    }
    with pytest.raises(ValueError, match="malformed acceptance criterion"):
        validate_extraction(data)


def test_validate_extraction_accepts_source_reference_on_epic_and_scenario():
    data = {
        "epics": [{"id": "E1", "title": "x", "source_reference": "4.1.A"}],
        "user_stories": [{
            "id": "S1", "epic_id": "E1", "title": "x", "description": "x",
            "acceptance_criteria": [],
            "scenarios": [{"title": "x", "given": "x", "when": "x", "then": "x", "source_reference": "4.1.A"}],
        }],
        "gaps": [],
    }
    validate_extraction(data)  # should not raise


def test_validate_extraction_rejects_non_string_source_reference_on_epic():
    data = {
        "epics": [{"id": "E1", "title": "x", "source_reference": 4}],
        "user_stories": [],
        "gaps": [],
    }
    with pytest.raises(ValueError, match="source_reference must be a string"):
        validate_extraction(data)


def test_validate_extraction_rejects_non_string_source_reference_on_scenario():
    data = {
        "epics": [{"id": "E1", "title": "x"}],
        "user_stories": [{
            "id": "S1", "epic_id": "E1", "title": "x", "description": "x",
            "acceptance_criteria": [],
            "scenarios": [{"title": "x", "given": "x", "when": "x", "then": "x", "source_reference": ["not", "a", "string"]}],
        }],
        "gaps": [],
    }
    with pytest.raises(ValueError, match="non-string source_reference"):
        validate_extraction(data)


# --- extract_requirements() ---

def test_extract_requirements_happy_path():
    # Four calls (draft, coverage audit, review, granularity audit) hit this
    # same fake client and get the same (already-valid) response, so usage
    # is the sum of four calls, not one — see REVIEW_SYSTEM_PROMPT /
    # _call_coverage_audit / _ensure_story_granularity. The granularity audit
    # reports everything already correctly split, so no repair call fires.
    client = _fake_client(VALID_FRESH_EXTRACTION)
    data, usage = extract_requirements("some SOW text", client, model="gpt-4o")

    assert data["epics"][0]["id"] == "E1"
    assert usage.prompt_tokens == 4000
    assert usage.completion_tokens == 1600


# --- retry on malformed model response ---
# Confirmed live: a real CR upload failed twice in a row with two different
# malformed-response symptoms, while an identical direct reproduction of the
# same request succeeded immediately after — the same non-determinism this
# file already documents elsewhere (see _call_llm's temperature comment),
# just surfacing as a broken response instead of an inconsistent-but-valid
# one. _call_llm/_call_with_tool now retry a few times before giving up.

def _malformed_json_response(prompt_tokens=100, completion_tokens=50):
    tool_call = SimpleNamespace(
        function=SimpleNamespace(name="record_extraction", arguments='{"epics": [truncated...')
    )
    message = SimpleNamespace(tool_calls=[tool_call], content="")
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def test_call_llm_retries_on_malformed_json_then_succeeds():
    call_count = {"n": 0}

    def create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _malformed_json_response()
        return _fake_response(VALID_FRESH_EXTRACTION)

    client = SimpleNamespace()
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    data, _usage = _call_llm("system prompt", "user prompt", client, "gpt-4o")

    assert call_count["n"] == 2
    assert data["epics"][0]["id"] == "E1"


def test_call_llm_raises_after_exhausting_retries_on_persistent_malformed_json():
    call_count = {"n": 0}

    def create(**kwargs):
        call_count["n"] += 1
        return _malformed_json_response()

    client = SimpleNamespace()
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    with pytest.raises(ValueError, match="malformed"):
        _call_llm("system prompt", "user prompt", client, "gpt-4o")

    assert call_count["n"] == 3  # _MAX_MALFORMED_RESPONSE_ATTEMPTS


def test_extract_requirements_rejects_invalid_model_output():
    bad = {"epics": [], "user_stories": [{"id": "S1", "epic_id": "MISSING", "title": "x", "description": "x", "acceptance_criteria": []}], "gaps": []}
    client = _fake_client(bad)
    with pytest.raises(ValueError, match="unknown epic_id"):
        extract_requirements("text", client, model="gpt-4o")


def test_extract_requirements_raises_if_no_tool_call():
    client = SimpleNamespace()
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))
    with pytest.raises(ValueError, match="tool call"):
        extract_requirements("text", client, model="gpt-4o")


# --- extract_change_request() ---

def test_extract_change_request_allows_reusing_existing_epic():
    cr_data = {
        "epics": [],
        "user_stories": [{
            "id": "S1", "epic_id": "E2", "title": "Assign startups to a subsidiary",
            "description": "As an Admin, I want to assign startups to a subsidiary.",
            "acceptance_criteria": [{"text": "Admin can assign each startup to a subsidiary.", "out_of_scope": False}],
        }],
        "gaps": [],
    }
    client = _fake_client(cr_data)
    existing = [ExistingEpic(external_id="E1", title="Jury Evaluation"), ExistingEpic(external_id="E2", title="Subsidiary Program")]

    data, usage = extract_change_request("CR text", existing, client, model="gpt-4o")

    assert data["user_stories"][0]["epic_id"] == "E2"
    # draft + coverage audit + review = 3 calls. The granularity audit is
    # skipped here (see _looks_already_well_split): this CR introduces no
    # new epics at all (its one story attaches to an existing baseline
    # epic), so there's nothing for that audit to find.
    assert usage.prompt_tokens == 3000


# --- _looks_already_well_split() — the granularity-audit skip heuristic ---

def test_looks_already_well_split_true_when_every_epic_has_two_plus_stories():
    data = {
        "epics": [{"id": "E1"}, {"id": "E2"}],
        "user_stories": [
            {"id": "S1", "epic_id": "E1"}, {"id": "S2", "epic_id": "E1"},
            {"id": "S3", "epic_id": "E2"}, {"id": "S4", "epic_id": "E2"},
        ],
    }
    assert _looks_already_well_split(data) is True


def test_looks_already_well_split_false_when_any_epic_has_exactly_one_story():
    """The exact ambiguous case the audit exists to resolve (a genuinely
    single-bullet epic vs. a missed split) — must never be skipped."""
    data = {
        "epics": [{"id": "E1"}, {"id": "E2"}],
        "user_stories": [
            {"id": "S1", "epic_id": "E1"}, {"id": "S2", "epic_id": "E1"},
            {"id": "S3", "epic_id": "E2"},  # only one story for E2
        ],
    }
    assert _looks_already_well_split(data) is False


def test_looks_already_well_split_true_when_no_new_epics_at_all():
    """A CR/suggestions batch that only attaches stories to existing
    baseline epics (no new epics in this batch) has nothing for the
    granularity audit to check either — vacuously well-split."""
    data = {"epics": [], "user_stories": [{"id": "S1", "epic_id": "E1"}]}
    assert _looks_already_well_split(data) is True


def test_extract_change_request_rejects_epic_id_not_in_existing_or_new():
    cr_data = {
        "epics": [{"id": "E2", "title": "New Epic"}],
        "user_stories": [{
            "id": "S1", "epic_id": "E99", "title": "x", "description": "x", "acceptance_criteria": [],
        }],
        "gaps": [],
    }
    client = _fake_client(cr_data)
    existing = [ExistingEpic(external_id="E1", title="Already Approved Epic")]

    with pytest.raises(ValueError, match="unknown epic_id"):
        extract_change_request("CR text", existing, client, model="gpt-4o")


def test_extract_change_request_prompt_includes_existing_epics():
    captured = {}

    def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        tool_choice = kwargs.get("tool_choice")
        requested_name = tool_choice["function"]["name"] if tool_choice else "record_extraction"
        if requested_name == "record_granularity_audit":
            return _fake_response(_NO_UNDERSPLIT_FINDING, tool_name=requested_name)
        return _fake_response(VALID_FRESH_EXTRACTION, tool_name=requested_name)

    client = SimpleNamespace()
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    existing = [ExistingEpic(external_id="E7", title="Existing Epic Title")]

    extract_change_request("CR text", existing, client, model="gpt-4o")

    # messages[0] is the system prompt, messages[1] is the user prompt containing the existing epics
    prompt_text = captured["messages"][1]["content"]
    assert "E7" in prompt_text
    assert "Existing Epic Title" in prompt_text


# --- mandatory coverage-audit + self-review pass ---

CORRECTED_EXTRACTION = {
    "epics": [{"id": "E1", "title": "Strategy Hierarchy", "assumptions": [], "dependencies": []}],
    "user_stories": [
        {
            "id": "S1",
            "epic_id": "E1",
            "title": "Configure Enterprise Strategy Hierarchy (corrected)",
            "description": "As the Strategy Execution Office, we want to configure the strategy hierarchy.",
            "scenarios": [],
            "acceptance_criteria": [
                {"text": "The strategy hierarchy is fully configured and approved.", "out_of_scope": False},
                {"text": "A criterion the review pass added.", "out_of_scope": False},
            ],
            "error_handling": [],
        }
    ],
    "gaps": [],
}


_NO_UNDERSPLIT_FINDING = {
    "epic_findings": [{"epic_id": "E1", "under_split": False, "missing_capabilities": []}]
}


def _sequenced_client(responses: list[dict], contents: list[str] | None = None, tool_names: list[str] | None = None):
    """A fake client returning a different response on each successive call."""
    calls = {"n": 0}
    contents = contents or ["(no coverage findings)"] * len(responses)
    tool_names = tool_names or ["record_extraction"] * len(responses)

    def create(**kwargs):
        i = calls["n"]
        data = responses[i]
        content = contents[i]
        tool_name = tool_names[i]
        calls["n"] += 1
        return _fake_response(data, content=content, tool_name=tool_name)

    client = SimpleNamespace()
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
    return client, calls


def test_extract_requirements_returns_the_reviewed_version_not_the_draft():
    client, calls = _sequenced_client(
        [VALID_FRESH_EXTRACTION, VALID_FRESH_EXTRACTION, CORRECTED_EXTRACTION, _NO_UNDERSPLIT_FINDING],
        tool_names=["record_extraction", "record_extraction", "record_extraction", "record_granularity_audit"],
    )

    data, _usage = extract_requirements("some SOW text", client, model="gpt-4o")

    # draft + coverage audit + review + granularity audit, all actually invoked
    assert calls["n"] == 4
    assert data["user_stories"][0]["title"] == "Configure Enterprise Strategy Hierarchy (corrected)"
    assert len(data["user_stories"][0]["acceptance_criteria"]) == 2


def test_extract_requirements_review_prompt_includes_source_draft_and_audit():
    captured = {}

    def fake_create(**kwargs):
        call_index = len(captured)
        captured[call_index] = kwargs["messages"]
        if call_index == 0:
            return _fake_response(VALID_FRESH_EXTRACTION)
        if call_index == 1:
            return _fake_response(VALID_FRESH_EXTRACTION, content="AUDIT: strategy hierarchy section is fully covered.")
        if call_index == 2:
            return _fake_response(CORRECTED_EXTRACTION)
        return _fake_response(_NO_UNDERSPLIT_FINDING, tool_name="record_granularity_audit")

    client = SimpleNamespace()
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=fake_create))

    extract_requirements("a very specific source sentence", client, model="gpt-4o")

    assert len(captured) == 4  # draft, coverage audit, review, granularity audit

    # the coverage audit call (index 1) received the draft + source, with its own system prompt
    audit_system_prompt = captured[1][0]["content"]
    audit_user_prompt = captured[1][1]["content"]
    assert audit_system_prompt != captured[0][0]["content"]  # not SYSTEM_PROMPT
    assert "a very specific source sentence" in audit_user_prompt
    assert "Configure Enterprise Strategy Hierarchy" in audit_user_prompt  # the draft, included for audit

    # the review call (index 2) received source + draft + the audit's own findings
    review_system_prompt = captured[2][0]["content"]
    review_user_prompt = captured[2][1]["content"]
    assert review_system_prompt != captured[0][0]["content"]  # not SYSTEM_PROMPT
    assert review_system_prompt != audit_system_prompt  # not COVERAGE_AUDIT_SYSTEM_PROMPT either
    assert "a very specific source sentence" in review_user_prompt
    assert "Configure Enterprise Strategy Hierarchy" in review_user_prompt
    assert "AUDIT: strategy hierarchy section is fully covered." in review_user_prompt


def test_extract_requirements_validates_the_reviewed_output_too():
    bad_review_output = {
        "epics": [],
        "user_stories": [{"id": "S1", "epic_id": "MISSING", "title": "x", "description": "x", "acceptance_criteria": []}],
        "gaps": [],
    }
    client, _calls = _sequenced_client([VALID_FRESH_EXTRACTION, VALID_FRESH_EXTRACTION, bad_review_output])

    with pytest.raises(ValueError, match="unknown epic_id"):
        extract_requirements("some SOW text", client, model="gpt-4o")


# --- generate_item_draft() ---

def _fake_tool_response(tool_name: str, tool_input: dict, prompt_tokens=500, completion_tokens=200):
    tool_call = SimpleNamespace(function=SimpleNamespace(name=tool_name, arguments=json.dumps(tool_input)))
    message = SimpleNamespace(tool_calls=[tool_call], content="")
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _fake_tool_client(tool_name: str, tool_input: dict):
    client = SimpleNamespace()
    response = _fake_tool_response(tool_name, tool_input)
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))
    return client


def test_generate_item_draft_epic():
    client = _fake_tool_client(
        "record_epic_draft",
        {"title": "Audit Logging", "assumptions": [], "dependencies": ["Requires SSO integration"]},
    )
    draft, usage = generate_item_draft("epic", "we need audit logging", client, model="gpt-4o")
    assert draft["title"] == "Audit Logging"
    assert draft["dependencies"] == ["Requires SSO integration"]
    assert usage.prompt_tokens == 500


def test_generate_item_draft_story():
    story_input = {
        "title": "Export audit log as CSV",
        "description": "As an Admin, I want to export the audit log as CSV, so that I can share it with auditors.",
        "scenarios": [
            {"title": "Export succeeds", "given": "I am on the audit log page", "when": "I click Export", "then": "a CSV downloads", "source_reference": ""}
        ],
        "acceptance_criteria": [{"text": "Clicking Export downloads a CSV of the visible audit log", "out_of_scope": False}],
        "error_handling": [],
    }
    client = _fake_tool_client("record_story_draft", story_input)
    draft, _usage = generate_item_draft(
        "story", "let admins export the audit log", client, model="gpt-4o",
        project_context="E1 — Audit Logging", parent_context="This story belongs under epic E1 — Audit Logging.",
    )
    assert draft["title"] == "Export audit log as CSV"
    assert draft["scenarios"][0]["source_reference"] == ""


def test_generate_item_draft_acceptance_criterion_forces_in_scope():
    client = _fake_tool_client("record_ac_draft", {"text": "Export is disabled while a filter error is showing"})
    draft, _usage = generate_item_draft("acceptance_criterion", "block export on filter errors", client, model="gpt-4o")
    assert draft == {"text": "Export is disabled while a filter error is showing", "out_of_scope": False}


def test_generate_item_draft_rejects_invalid_kind():
    with pytest.raises(ValueError, match="Invalid kind"):
        generate_item_draft("gap", "something", _fake_tool_client("record_epic_draft", {}), model="gpt-4o")


# --- generate_suggestions() ---

_FINAL_DATA = {
    "epics": [{"id": "E1", "title": "Strategy Hierarchy"}],
    "user_stories": [
        {"id": "S1", "epic_id": "E1", "title": "Configure strategy hierarchy", "description": "...", "scenarios": [], "acceptance_criteria": [], "error_handling": []}
    ],
}


def test_generate_suggestions_returns_new_stories_attached_to_existing_epic():
    suggestion_payload = {
        "epics": [],
        "user_stories": [
            {
                "id": "S2",
                "epic_id": "E1",
                "title": "Bulk-import strategic objectives from a spreadsheet",
                "description": "As the Strategy Execution Office, I want to bulk-import objectives, so that setup is faster.",
                "scenarios": [],
                "acceptance_criteria": [{"text": "A CSV of objectives can be imported in one action", "out_of_scope": False}],
                "error_handling": [],
            }
        ],
        "gaps": [],
    }
    client = _fake_client(suggestion_payload)
    data, usage = generate_suggestions("source text", _FINAL_DATA, client, model="gpt-4o")
    assert len(data["user_stories"]) == 1
    assert data["user_stories"][0]["epic_id"] == "E1"
    assert usage.prompt_tokens == 1000


def test_generate_suggestions_silently_drops_empty_new_epic():
    suggestion_payload = {
        "epics": [{"id": "E2", "title": "Reporting", "assumptions": [], "dependencies": [], "source_reference": ""}],
        "user_stories": [],  # E2 has no story — should be dropped, not raised
        "gaps": [],
    }
    client = _fake_client(suggestion_payload)
    data, _usage = generate_suggestions("source text", _FINAL_DATA, client, model="gpt-4o")
    assert data["epics"] == []


# --- mojibake sanitization ---

def test_extract_requirements_repairs_truncated_unicode_escape_in_epic_title():
    """Observed directly against a real project: OpenAI's structured
    output truncated a \u2013 (en dash) escape down to a bare U+0013
    control character while the model was copying a section heading
    verbatim — which renders as a 'missing glyph' box in the browser since
    a raw control character has no glyph in any font. The fix repairs it
    right where the JSON is parsed, before it ever reaches the database."""
    corrupted = {
        "epics": [{"id": "E1", "title": "Core Strategy Execution Model \x13 Phase 1", "assumptions": [], "dependencies": []}],
        "user_stories": [{
            "id": "S1", "epic_id": "E1", "title": "x",
            "description": "As a user, I want x, so that y.",
            "scenarios": [], "acceptance_criteria": [{"text": "x", "out_of_scope": False}], "error_handling": [],
        }],
        "gaps": [],
    }
    client = _fake_client(corrupted)
    data, _usage = extract_requirements("some SOW text", client, model="gpt-4o")
    assert data["epics"][0]["title"] == "Core Strategy Execution Model – Phase 1"
    assert "\x13" not in data["epics"][0]["title"]


def test_extract_requirements_repairs_truncated_unicode_escape_nested_in_acceptance_criteria():
    """Same failure mode as the epic-title case above, but nested inside a
    story's acceptance_criteria list — confirmed directly to slip past a
    naive top-level-only fix: acceptance_criteria/scenarios/error_handling
    are JSON columns, so the corrupted character round-trips through an
    extra layer of JSON encoding on the way to the database. The sanitizer
    must recurse into nested structures, not just scan top-level fields."""
    corrupted = {
        "epics": [{"id": "E1", "title": "x", "assumptions": [], "dependencies": []}],
        "user_stories": [{
            "id": "S1", "epic_id": "E1", "title": "x",
            "description": "As a user, I want x, so that y.",
            "scenarios": [],
            "acceptance_criteria": [
                {"text": "All error messages are clear, specific, and actionable \x13 never generic.", "out_of_scope": False}
            ],
            "error_handling": [],
        }],
        "gaps": [],
    }
    client = _fake_client(corrupted)
    data, _usage = extract_requirements("some SOW text", client, model="gpt-4o")
    ac_text = data["user_stories"][0]["acceptance_criteria"][0]["text"]
    assert ac_text == "All error messages are clear, specific, and actionable – never generic."
    assert "\x13" not in ac_text


def test_generate_suggestions_renumbers_new_epic_id_colliding_with_existing():
    """Confirmed directly against a real project: the model proposed a new
    epic reusing an id ("E1") that already belonged to an existing epic,
    which made validate_extraction() reject the whole batch — silently,
    since a suggestions failure is swallowed rather than retried. The fix
    renumbers the collision deterministically instead of trusting the
    prompt's "don't reuse an existing id" instruction to always hold."""
    suggestion_payload = {
        "epics": [{"id": "E1", "title": "New Capability Area", "assumptions": [], "dependencies": [], "source_reference": ""}],
        "user_stories": [
            {
                "id": "S1", "epic_id": "E1", "title": "Do the new thing",
                "description": "As a user, I want the new thing, so that I benefit.",
                "scenarios": [], "acceptance_criteria": [{"text": "The new thing works", "out_of_scope": False}],
                "error_handling": [],
            }
        ],
        "gaps": [],
    }
    client = _fake_client(suggestion_payload)
    data, _usage = generate_suggestions("source text", _FINAL_DATA, client, model="gpt-4o")

    assert len(data["epics"]) == 1
    new_epic_id = data["epics"][0]["id"]
    assert new_epic_id != "E1"  # renumbered away from the collision
    assert data["user_stories"][0]["epic_id"] == new_epic_id  # reference updated to match


def test_generate_suggestions_renumbers_collision_with_reserved_id_not_in_final_data():
    """Confirmed directly against a real project: an earlier, still-pending
    (not yet accepted/dismissed) suggestion epic "E9" is deliberately
    excluded from final_data (an unconfirmed suggestion shouldn't count as
    "already covered" when this call decides what's missing) — but "E9" is
    still a real, persisted row for this document, so a new batch reusing
    "E9" must still be caught. Without reserved_epic_ids, this collision was
    invisible to both _renumber_colliding_ids and validate_extraction (both
    keyed off final_data's epics alone) and only surfaced as a raw database
    UNIQUE-constraint crash when persisted."""
    suggestion_payload = {
        "epics": [{"id": "E9", "title": "Configure security and compliance features", "assumptions": [], "dependencies": [], "source_reference": ""}],
        "user_stories": [
            {
                "id": "S1", "epic_id": "E9", "title": "Do the new thing",
                "description": "As a user, I want the new thing, so that I benefit.",
                "scenarios": [], "acceptance_criteria": [{"text": "The new thing works", "out_of_scope": False}],
                "error_handling": [],
            }
        ],
        "gaps": [],
    }
    client = _fake_client(suggestion_payload)
    # "E9" is NOT in _FINAL_DATA["epics"] (simulating the pending-suggestion
    # exclusion) — only reserved_epic_ids knows it's taken.
    data, _usage = generate_suggestions(
        "source text", _FINAL_DATA, client, model="gpt-4o", reserved_epic_ids={"E9"}
    )

    assert len(data["epics"]) == 1
    new_epic_id = data["epics"][0]["id"]
    assert new_epic_id != "E9"  # renumbered away from the reserved-but-hidden collision
    assert data["user_stories"][0]["epic_id"] == new_epic_id


def test_generate_suggestions_renumbers_duplicate_story_id_within_batch():
    suggestion_payload = {
        "epics": [],
        "user_stories": [
            {
                "id": "S1", "epic_id": "E1", "title": "First new story",
                "description": "As a user, I want a, so that b.",
                "scenarios": [], "acceptance_criteria": [{"text": "a happens", "out_of_scope": False}], "error_handling": [],
            },
            {
                "id": "S1", "epic_id": "E1", "title": "Second new story",  # duplicate id
                "description": "As a user, I want c, so that d.",
                "scenarios": [], "acceptance_criteria": [{"text": "c happens", "out_of_scope": False}], "error_handling": [],
            },
        ],
        "gaps": [],
    }
    client = _fake_client(suggestion_payload)
    data, _usage = generate_suggestions("source text", _FINAL_DATA, client, model="gpt-4o")

    story_ids = [s["id"] for s in data["user_stories"]]
    assert len(story_ids) == len(set(story_ids))  # no duplicates survive


def test_generate_item_draft_scenario():
    client = _fake_tool_client(
        "record_scenario_draft",
        {"title": "Export succeeds", "given": "I am on the report page", "when": "I click Export", "then": "a file downloads"},
    )
    draft, _usage = generate_item_draft("scenario", "exporting a report", client, model="gpt-4o")
    assert draft["title"] == "Export succeeds"
    assert draft["source_reference"] == ""  # not grounded in a document — never a real citation


def test_generate_item_draft_error_handling():
    client = _fake_tool_client("record_error_handling_draft", {"condition": "export fails", "message": "[TBD: exact copy]"})
    draft, _usage = generate_item_draft("error_handling", "handle export failures", client, model="gpt-4o")
    assert draft == {"condition": "export fails", "message": "[TBD: exact copy]"}


def test_generate_item_draft_regenerate_raises_temperature_and_includes_previous_draft():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _fake_tool_response("record_epic_draft", {"title": "A different take", "assumptions": [], "dependencies": []})

    client = SimpleNamespace()
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    previous = {"title": "First attempt", "assumptions": [], "dependencies": []}
    draft, _usage = generate_item_draft("epic", "audit logging", client, model="gpt-4o", previous_draft=previous)

    assert captured["temperature"] == 0.9
    assert "First attempt" in captured["messages"][1]["content"]
    assert "meaningfully different" in captured["messages"][1]["content"]
    assert draft["title"] == "A different take"


def test_generate_item_draft_first_attempt_stays_at_temperature_zero():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _fake_tool_response("record_epic_draft", {"title": "x", "assumptions": [], "dependencies": []})

    client = SimpleNamespace()
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    generate_item_draft("epic", "audit logging", client, model="gpt-4o")
    assert captured["temperature"] == 0


# --- generate_clarifying_questions() ---
# Two real calls now (see generate_clarifying_questions()'s own docstring for
# why): the material-gap call and the fixed-checklist baseline audit call.
# Both share the same tool name ("record_clarifying_questions"), so a fake
# client distinguishes them by system-prompt content, not tool_choice.


def _fake_branching_tool_client(gap_payload: dict, baseline_payload: dict, prompt_tokens=500, completion_tokens=200):
    client = SimpleNamespace()

    def create(**kwargs):
        system_content = kwargs["messages"][0]["content"]
        payload = baseline_payload if "fixed checklist" in system_content else gap_payload
        return _fake_tool_response(
            "record_clarifying_questions", payload, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )

    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
    return client


def test_generate_clarifying_questions_merges_both_calls():
    gap_payload = {
        "questions": [
            {
                "question": "When a client cancels an order, should the refund happen automatically or does someone need to approve it first?",
                "topic_area": "Order cancellation",
                "why_it_matters": "Determines whether an approval step needs to be built into the cancellation flow.",
            }
        ]
    }
    baseline_payload = {
        "questions": [
            {
                "question": "Is there any sensitive personal information involved, like payment details?",
                "topic_area": "Security & data privacy",
                "why_it_matters": "Determines what protections need to be built in.",
            }
        ]
    }
    client = _fake_branching_tool_client(gap_payload, baseline_payload)
    questions, usage = generate_clarifying_questions("some staged resource text", client, model="gpt-4o")
    assert len(questions) == 2
    topic_areas = {q["topic_area"] for q in questions}
    assert topic_areas == {"Order cancellation", "Security & data privacy"}
    # usage is summed across both calls
    assert usage.prompt_tokens == 1000


def test_generate_clarifying_questions_can_return_empty_list():
    client = _fake_tool_client("record_clarifying_questions", {"questions": []})
    questions, _usage = generate_clarifying_questions("thorough staged resource text", client, model="gpt-4o")
    assert questions == []


# --- ensure_standing_policy_coverage() ---

_POLICY_COVERAGE_DATA = {
    "epics": [{"id": "E1", "title": "Expense Claims", "assumptions": [], "dependencies": []}],
    "user_stories": [
        {
            "id": "S1", "epic_id": "E1", "title": "Submit an expense claim",
            "description": "As a user, I want to submit an expense claim, so that I can get reimbursed.",
            "scenarios": [], "acceptance_criteria": [{"text": "A claim can be submitted", "out_of_scope": False}],
            "error_handling": [],
        }
    ],
    "gaps": [],
}


def test_ensure_standing_policy_coverage_is_a_noop_with_no_policies():
    data, usages = ensure_standing_policy_coverage(_POLICY_COVERAGE_DATA, [], client=None, model="gpt-4o")
    assert data is _POLICY_COVERAGE_DATA
    assert usages == []


def test_ensure_standing_policy_coverage_skips_repair_when_already_covered():
    def create(**kwargs):
        tool_choice = kwargs["tool_choice"]
        assert tool_choice["function"]["name"] == "record_policy_coverage_audit"
        return _fake_tool_response("record_policy_coverage_audit", {"uncovered_policy_titles": []})

    client = SimpleNamespace()
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    data, usages = ensure_standing_policy_coverage(
        _POLICY_COVERAGE_DATA, [("Accessibility default", "Meet WCAG 2.1 AA.")], client, model="gpt-4o"
    )
    assert data is _POLICY_COVERAGE_DATA  # untouched — no repair call fired
    assert len(usages) == 1  # audit call only


def test_ensure_standing_policy_coverage_adds_story_for_uncovered_policy():
    repaired = {
        "epics": _POLICY_COVERAGE_DATA["epics"],
        "user_stories": _POLICY_COVERAGE_DATA["user_stories"] + [
            {
                "id": "S2", "epic_id": "E1", "title": "Meet accessibility standard",
                "description": "As a user, I want the interface to be accessible, so that I can use it regardless of ability.",
                "scenarios": [],
                "acceptance_criteria": [{"text": "All screens meet WCAG 2.1 AA", "out_of_scope": False}],
                "error_handling": [],
            }
        ],
        "gaps": [],
    }

    audit_calls = {"count": 0}

    def create(**kwargs):
        tool_choice = kwargs["tool_choice"]
        name = tool_choice["function"]["name"]
        if name == "record_policy_coverage_audit":
            audit_calls["count"] += 1
            # Uncovered on the first check, covered once the repair below has run —
            # otherwise the loop (same _MAX_*_ATTEMPTS retry shape as the rest of
            # this pipeline) would keep repairing past the first, already-fixed pass.
            titles = ["Accessibility default"] if audit_calls["count"] == 1 else []
            return _fake_tool_response(name, {"uncovered_policy_titles": titles})
        return _fake_tool_response(name, repaired)

    client = SimpleNamespace()
    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    data, usages = ensure_standing_policy_coverage(
        _POLICY_COVERAGE_DATA, [("Accessibility default", "Meet WCAG 2.1 AA.")], client, model="gpt-4o"
    )
    assert len(data["user_stories"]) == 2
    assert data["user_stories"][1]["title"] == "Meet accessibility standard"
    assert len(usages) == 3  # 1st audit (uncovered) + repair + 2nd audit (now covered)


# --- review_source_material() / review_output_stories() / review_advisory_artifacts() ---
# Each of these agents' tool schema declares clarity_score/specificity_score/
# artifact_quality_score as a plain "integer" with no min/max — OpenAI's
# strict mode doesn't enforce a numeric range on that type, so each
# function clamps into [0, 100] itself. These tests confirm the clamp holds
# even when a fake model response supplies an out-of-range integer.


def test_review_source_material_clamps_score_and_returns_issues():
    client = _fake_tool_client(
        "record_source_material_review",
        {"clarity_score": 999, "summary": "Very clear.", "issues": ["Nothing to report."]},
    )
    score, summary, issues, usage = review_source_material("some source text", client, model="gpt-4o")
    assert score == 100
    assert summary == "Very clear."
    assert issues == ["Nothing to report."]
    assert usage.prompt_tokens == 500


def test_review_source_material_clamps_negative_score():
    client = _fake_tool_client(
        "record_source_material_review",
        {"clarity_score": -20, "summary": "Unusable.", "issues": ["Source text is empty."]},
    )
    score, _summary, _issues, _usage = review_source_material("", client, model="gpt-4o")
    assert score == 0


def test_review_output_stories_clamps_score_and_returns_weak_items():
    client = _fake_tool_client(
        "record_output_story_review",
        {
            "specificity_score": 150,
            "summary": "Mostly generic.",
            "weak_items": [{"external_id": "S2", "reason": "AC restates the title."}],
        },
    )
    score, summary, weak_items, _usage = review_output_stories(
        [{"id": "E1", "title": "Epic"}],
        [{"id": "S2", "epic_id": "E1", "title": "Story", "description": "", "acceptance_criteria": []}],
        client,
        model="gpt-4o",
    )
    assert score == 100
    assert summary == "Mostly generic."
    assert weak_items == [{"external_id": "S2", "reason": "AC restates the title."}]


def test_review_advisory_artifacts_clamps_score_and_returns_issues():
    client = _fake_tool_client(
        "record_artifact_quality_review",
        {"artifact_quality_score": -5, "summary": "Weak gaps.", "issues": ["Gap G1 is too vague."]},
    )
    score, summary, issues, _usage = review_advisory_artifacts(
        gaps=[{"id": "G1", "description": "needs more detail", "severity": "low", "status": "open"}],
        suggestions=[],
        policy_stories=[],
        client=client,
        model="gpt-4o",
    )
    assert score == 0
    assert summary == "Weak gaps."
    assert issues == ["Gap G1 is too vague."]
