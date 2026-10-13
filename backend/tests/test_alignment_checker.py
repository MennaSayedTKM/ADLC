"""
Tests for ai/vision/alignment_checker.py. The OpenAI client is mocked
throughout — no network calls, per the brief's "mock the OpenAI client"
requirement.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from ai.vision.alignment_checker import ApprovedStory, check_alignment, validate_alignment

STORIES = [
    ApprovedStory("S1", "As a user, I can log in with email/password.", ["Shows an error on wrong password"]),
    ApprovedStory("S2", "As a user, I can reset my password via email.", []),
]


def _fake_openai_client(content: str, prompt_tokens=600, completion_tokens=200):
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )
    return client


def test_validate_alignment_accepts_well_formed_data():
    validate_alignment(
        {"status": "partial", "findings": [{"requirement_id": "S1", "issue": "x", "recommendation": "y"}]},
        valid_requirement_ids={"S1", "S2"},
    )  # should not raise


def test_validate_alignment_rejects_bad_status():
    with pytest.raises(ValueError, match="status"):
        validate_alignment({"status": "kinda", "findings": []}, valid_requirement_ids=set())


def test_validate_alignment_rejects_malformed_finding():
    with pytest.raises(ValueError, match="Malformed finding"):
        validate_alignment(
            {"status": "misaligned", "findings": [{"requirement_id": "S1", "issue": "x"}]},
            valid_requirement_ids={"S1"},
        )


def test_check_alignment_parses_valid_response():
    content = (
        '{"status": "partial", "findings": '
        '[{"requirement_id": "S1", "issue": "No error state shown", '
        '"recommendation": "Add an inline error message below the password field"}]}'
    )
    client = _fake_openai_client(content)

    data, usage = check_alignment(Image.new("RGB", (10, 10)), STORIES, client, model="gpt-4o")

    assert data["status"] == "partial"
    assert data["findings"][0]["requirement_id"] == "S1"
    assert usage.prompt_tokens == 600
    client.chat.completions.create.assert_called_once()


def test_check_alignment_allows_unknown_requirement_id_as_advisory():
    """Findings referencing an id outside the approved set are soft slips, not hard failures."""
    content = (
        '{"status": "aligned", "findings": '
        '[{"requirement_id": "S999", "issue": "x", "recommendation": "y"}]}'
    )
    client = _fake_openai_client(content)

    data, _usage = check_alignment(Image.new("RGB", (10, 10)), STORIES, client, model="gpt-4o")
    assert data["findings"][0]["requirement_id"] == "S999"


def test_validate_alignment_accepts_null_bounding_box():
    validate_alignment(
        {
            "status": "misaligned",
            "findings": [
                {"requirement_id": "S1", "issue": "x", "recommendation": "y", "bounding_box": None}
            ],
        },
        valid_requirement_ids={"S1"},
    )  # should not raise


def test_validate_alignment_accepts_well_formed_bounding_box():
    validate_alignment(
        {
            "status": "partial",
            "findings": [
                {
                    "requirement_id": "S1",
                    "issue": "x",
                    "recommendation": "y",
                    "bounding_box": {"top": 10, "left": 5, "bottom": 30, "right": 40},
                }
            ],
        },
        valid_requirement_ids={"S1"},
    )  # should not raise


@pytest.mark.parametrize(
    "bad_box",
    [
        {"top": 10, "left": 5, "bottom": 30},  # missing "right"
        {"top": 10, "left": 5, "bottom": 30, "right": "far"},  # non-numeric
        {"top": 10, "left": 5, "bottom": 30, "right": 150},  # out of 0-100 range
        {"top": 30, "left": 5, "bottom": 10, "right": 40},  # bottom <= top, zero/negative area
    ],
)
def test_validate_alignment_rejects_malformed_bounding_box(bad_box):
    with pytest.raises(ValueError, match="bounding_box"):
        validate_alignment(
            {
                "status": "partial",
                "findings": [
                    {"requirement_id": "S1", "issue": "x", "recommendation": "y", "bounding_box": bad_box}
                ],
            },
            valid_requirement_ids={"S1"},
        )


def test_check_alignment_raises_over_inline_story_threshold():
    from ai.vision import alignment_checker

    too_many = [ApprovedStory(f"S{i}", "x", []) for i in range(alignment_checker.ALIGNMENT_MAX_STORIES_INLINE + 1)]
    client = _fake_openai_client('{"status": "aligned", "findings": []}')

    with pytest.raises(ValueError, match="ALIGNMENT_MAX_STORIES_INLINE"):
        check_alignment(Image.new("RGB", (10, 10)), too_many, client, model="gpt-4o")
    client.chat.completions.create.assert_not_called()


# A screen that implements none of the approved stories used to come back
# "aligned" (nothing relevant to it was unmet). The model now names the
# stories a screen implements, and code enforces the verdict when it names none.

def test_check_alignment_marks_a_screen_tied_to_no_story_misaligned():
    client = _fake_openai_client('{"status": "aligned", "related_requirement_ids": [], "findings": []}')

    data, _usage = check_alignment(Image.new("RGB", (10, 10)), STORIES, client, model="gpt-4o")

    assert data["status"] == "misaligned"
    assert len(data["findings"]) == 1
    assert data["findings"][0]["requirement_id"] is None
    assert "doesn't correspond to any approved requirement" in data["findings"][0]["issue"]


def test_check_alignment_keeps_the_models_own_untraced_finding():
    content = (
        '{"status": "misaligned", "related_requirement_ids": [], "findings": '
        '[{"requirement_id": null, "issue": "This is a StratAlign sign-in page, not part of this platform.", '
        '"recommendation": "Upload this project\'s screens."}]}'
    )
    client = _fake_openai_client(content)

    data, _usage = check_alignment(Image.new("RGB", (10, 10)), STORIES, client, model="gpt-4o")

    assert data["status"] == "misaligned"
    assert [f["issue"] for f in data["findings"]] == ["This is a StratAlign sign-in page, not part of this platform."]


def test_check_alignment_keeps_aligned_for_a_screen_that_implements_a_story():
    client = _fake_openai_client('{"status": "aligned", "related_requirement_ids": ["S1"], "findings": []}')

    data, _usage = check_alignment(Image.new("RGB", (10, 10)), STORIES, client, model="gpt-4o")

    assert data["status"] == "aligned"
    assert data["findings"] == []


def test_check_alignment_counts_a_finding_against_a_story_as_related():
    content = (
        '{"status": "partial", "findings": '
        '[{"requirement_id": "S2", "issue": "No reset link", "recommendation": "Add one"}]}'
    )
    client = _fake_openai_client(content)

    data, _usage = check_alignment(Image.new("RGB", (10, 10)), STORIES, client, model="gpt-4o")

    assert data["status"] == "partial"
    assert data["related_requirement_ids"] == ["S2"]


def test_check_alignment_tells_the_model_which_platform_the_design_is_for():
    from ai.vision.alignment_checker import PlatformContext

    client = _fake_openai_client('{"status": "aligned", "related_requirement_ids": ["S1"], "findings": []}')

    check_alignment(
        Image.new("RGB", (10, 10)), STORIES, client, model="gpt-4o",
        platform=PlatformContext(name="Startup Growth Platform", vision="Supports startups from registration to funding."),
    )

    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"][0]["text"]
    assert 'This design is for the platform "Startup Growth Platform"' in prompt
    assert "Supports startups from registration to funding." in prompt
    assert "related_requirement_ids" in prompt
