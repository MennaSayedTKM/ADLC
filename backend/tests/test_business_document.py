"""
Tests for business_document.py (stakeholder-facing restructuring of an
approved requirements version) and the Confluence page built from it. Pure
functions over unsaved model instances — no DB, OpenAI or embed server.
"""
from datetime import datetime, timezone

from app.db.models import Document, Gap, Project, RequirementItem
from app.services.business_document import _requirement_from_story, build_business_document
from app.services.confluence_export import build_version_page_html, version_page_title


def _story(description, **kwargs):
    return RequirementItem(external_id="S1", type="story", text="Title", description=description, **kwargs)


# --- story -> standard user story + source ---

def test_user_story_kept_in_standard_format():
    req = _requirement_from_story(
        "BR-1.1",
        _story(
            "As a startup, I want to create and edit my company profile, "
            "so that I can complete my profile at my own pace."
        ),
    )
    assert req.stakeholder == "Startup"
    assert req.user_story == (
        "As a startup, I want to create and edit my company profile, "
        "so that I can complete my profile at my own pace."
    )
    assert req.description is None


def test_user_story_without_benefit_still_parses():
    req = _requirement_from_story("BR-1.1", _story("As a user, I can log in."))
    assert req.user_story == "As a user, I can log in."


def test_non_template_description_is_shown_verbatim():
    req = _requirement_from_story("BR-1.1", _story("Users log in with email and password."))
    assert req.description == "Users log in with email and password."
    assert req.user_story is None and req.stakeholder is None


def test_story_without_description_keeps_only_title():
    req = _requirement_from_story("BR-1.1", _story(None))
    assert req.title == "Title"
    assert req.user_story is None and req.description is None


def test_source_per_origin():
    def source(origin, from_gap=False):
        return _requirement_from_story("BR-1.1", _story(None, origin=origin), from_gap).source

    assert source("extracted") == "Original requirements"
    assert source("ai_suggestion") == "AI suggestion"
    assert source("pm_manual") == "Review"
    assert source("pm_ai_assisted") == "Review"
    assert source("pm_ai_assisted", from_gap=True) == "AI gap"


def test_story_resolved_from_a_gap_is_sourced_to_the_gap():
    project, v1, v2, epics, stories, gaps = _fixture()
    gaps[2].resolved_as_item_id = "s1"
    bdoc = build_business_document(project, v2, epics, stories, gaps)
    assert bdoc.areas[0].requirements[0].source == "AI gap"
    assert bdoc.areas[1].requirements[0].source == "Original requirements"


# --- document structure ---

def _fixture():
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    project = Project(name="Acme Portal")
    v1 = Document(id="d1", version=1, approval_status="approved", source_filename="sow.pdf", updated_at=now)
    v2 = Document(
        id="d2",
        version=2,
        approval_status="approved",
        source_filename="sow.pdf",
        previous_version_id="d1",
        updated_at=now,
    )
    epic = RequirementItem(
        id="e1",
        type="epic",
        external_id="E1",
        text="Company profiles",
        source_reference="4.1",
        assumptions=["Startups already have accounts"],
        dependencies=["CRM export"],
    )
    stories = [
        RequirementItem(
            id="s1",
            type="story",
            external_id="S1",
            parent_id="e1",
            text="Edit profile",
            description="As a startup, I want to edit my profile, so that investors see current details.",
            acceptance_criteria=[
                {"text": "Changes save immediately", "out_of_scope": False},
                {"text": "Profile version history", "out_of_scope": True},
            ],
            scenarios=[{"title": "t", "given": "GIVEN-TEXT", "when": "w", "then": "t", "source_reference": None}],
            error_handling=[{"condition": "c", "message": "ERROR-MESSAGE"}],
        ),
        RequirementItem(id="s2", type="story", external_id="S2", parent_id=None, text="Orphan story"),
    ]
    gaps = [
        Gap(description="Low one", severity="low", status="open", location="§2"),
        Gap(description="High one", severity="high", status="open", page=3),
        Gap(description="Already resolved", severity="high", status="resolved"),
    ]
    return project, v1, v2, [epic], stories, gaps


def test_builds_areas_scope_notes_issues_and_history():
    project, v1, v2, epics, stories, gaps = _fixture()
    bdoc = build_business_document(project, v2, epics, stories, gaps, [v1, v2])

    assert [a.title for a in bdoc.areas] == ["Company profiles", "Other requirements"]
    assert [r.ref for r in bdoc.areas[0].requirements] == ["BR-1.1"]
    assert bdoc.areas[1].requirements[0].ref == "BR-2.1"  # stories with no epic aren't dropped

    req = bdoc.areas[0].requirements[0]
    assert req.acceptance_criteria == ["Changes save immediately"]
    assert [(x.requirement_ref, x.text) for x in bdoc.out_of_scope] == [("BR-1.1", "Profile version history")]

    assert [(n.area, n.text) for n in bdoc.assumptions] == [("Company profiles", "Startups already have accounts")]
    assert [(n.area, n.text) for n in bdoc.dependencies] == [("Company profiles", "CRM export")]

    # open gaps only, highest priority first
    assert [(i.priority, i.description, i.location) for i in bdoc.open_issues] == [
        ("High", "High one", "Page 3"),
        ("Low", "Low one", "§2"),
    ]
    assert [v.version for v in bdoc.version_history] == [1, 2]
    assert bdoc.approved_on == "September 1, 2026"
    assert "2 capability areas and 2 business requirements" in bdoc.purpose
    assert "2 open issues that need stakeholder input" in bdoc.purpose


def test_confluence_page_is_business_document_without_delivery_detail():
    project, v1, v2, epics, stories, gaps = _fixture()
    bdoc = build_business_document(project, v2, epics, stories, gaps, [v1, v2])
    html = build_version_page_html(bdoc, supersedes_url="https://x/prev")

    assert version_page_title(bdoc) == "Acme Portal — Business Requirements v2 (Approved September 1, 2026)"
    for expected in (
        "1. Overview and Scope",
        "BR-1.1",
        "Source",
        "Original requirements",
        "As a startup, I want to edit my profile, so that investors see current details.",
        "Profile version history",
        "4. Open Issues Requiring Stakeholder Input",
        "High one",
        "6. Stakeholder Sign-off",
        "supersedes",
    ):
        assert expected in html, expected
    assert "GIVEN-TEXT" not in html
    assert "ERROR-MESSAGE" not in html
    assert "Already resolved" not in html


def test_confluence_escapes_user_text():
    project, v1, v2, epics, stories, gaps = _fixture()
    stories[0].text = "Edit <profile> & save"
    html = build_version_page_html(build_business_document(project, v2, epics, stories, gaps))
    assert "Edit &lt;profile&gt; &amp; save" in html
