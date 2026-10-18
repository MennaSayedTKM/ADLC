"""
dev_story_generator.py
Breaks the approved user stories of one epic into development work, the way
the team's Jira is organised: each user story becomes one or more development
stories (Jira Stories, business level, under the same epic), and each
development story gets one or more technical tasks (Jira Sub-tasks). The
detailed coding prompt for each task is written separately, by a stronger
model (coding_prompt_generator.py); this step only plans the work.

Also reads an uploaded tech-stack document into the per-area tech profile
(read_tech_profile), so the company can upload what it has instead of typing.
"""

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import (  # noqa: E402
    DEV_STORY_MAX_TOKENS,
    DEV_STORY_MODEL,
    TECH_PROFILE_MAX_TOKENS,
    TECH_PROFILE_MODEL,
)

from .common import Usage  # noqa: E402
from .requirements_extractor import _create_and_parse_tool_call  # noqa: E402

# The parts of a stack a coding prompt needs to know, in the order shown to people.
TECH_AREAS: dict[str, str] = {
    "frontend": "Frontend",
    "backend": "Backend",
    "database": "Database and storage",
    "infrastructure": "Hosting and infrastructure",
    "authentication": "Authentication and access",
    "integrations": "Integrations and messaging",
    "testing": "Testing",
    "ci_cd": "CI/CD and delivery",
    "conventions": "Coding conventions and standards",
}

TASK_AREAS = ("frontend", "backend", "data", "integration", "infrastructure", "testing")

STORY_POINTS = (1, 2, 3, 5, 8, 13)


# ── Development stories ──────────────────────────────────────────────────────

_DEV_STORY_SYSTEM_PROMPT = (
    "You are a senior tech lead planning delivery work from approved user stories, for a "
    "team that tracks work in Jira as Epic -> Story -> Sub-task.\n\n"
    "For every user story you are given, write one or more DEVELOPMENT STORIES:\n"
    "- One development story per independently deliverable slice of the user story. Most user "
    "stories become exactly one; split only when the story bundles pieces a team would ship "
    "separately (for example capture vs. approval workflow). Never merge two user stories.\n"
    "- title: a short imperative ticket title.\n"
    "- objective: 2-4 sentences on what is built and why, grounded in the user story.\n"
    "- scope: what is in and out of this development story, as short bullet lines.\n"
    "- acceptance_criteria: testable statements, carrying over the user story's criteria and "
    "adding only what the split makes necessary.\n"
    "- story_points: relative size on the Fibonacci scale (1, 2, 3, 5, 8, 13).\n"
    "- labels: 2-5 short lowercase-hyphenated labels (feature area, main technical area).\n"
    "- tasks: the technical sub-tasks that deliver it, one per technical area that has real "
    "work (frontend, backend, data, integration, infrastructure, testing). Each task has a "
    "short imperative title and a 1-3 sentence summary of exactly what that task covers, so "
    "the tasks of one story don't overlap. Usually 1-4 tasks; a pure UI change can be a single "
    "frontend task.\n\n"
    "Stay inside the user stories: don't invent features, integrations or business rules "
    "they don't state. Technology choices are not decided here — describe tasks in terms of "
    "what they build, not which framework builds it. Use the story ids exactly as given. "
    "Return via the record_dev_stories tool."
)

_DEV_STORY_PARAMETERS = {
    "type": "object",
    "properties": {
        "dev_stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_story": {"type": "string"},
                    "title": {"type": "string"},
                    "objective": {"type": "string"},
                    "scope": {"type": "array", "items": {"type": "string"}},
                    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                    "story_points": {"type": "integer", "enum": list(STORY_POINTS)},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "summary": {"type": "string"},
                                "area": {"type": "string", "enum": list(TASK_AREAS)},
                            },
                            "required": ["title", "summary", "area"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "source_story", "title", "objective", "scope", "acceptance_criteria",
                    "story_points", "labels", "tasks",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["dev_stories"],
    "additionalProperties": False,
}

_DEV_STORY_TOOL = {
    "type": "function",
    "function": {
        "name": "record_dev_stories",
        "description": "Record the development stories and their technical tasks for the given user stories.",
        "parameters": _DEV_STORY_PARAMETERS,
        "strict": True,
    },
}


def _format_user_story(story: dict[str, Any]) -> str:
    lines = [f"{story['external_id']}: {story['title']}"]
    if story.get("description"):
        lines.append(f"  Story: {story['description']}")
    criteria = [c["text"] for c in (story.get("acceptance_criteria") or []) if not c.get("out_of_scope")]
    if criteria:
        lines.append("  Acceptance criteria:")
        lines.extend(f"    - {c}" for c in criteria)
    for sc in story.get("scenarios") or []:
        lines.append(f"  Scenario '{sc['title']}': Given {sc['given']} / When {sc['when']} / Then {sc['then']}")
    for eh in story.get("error_handling") or []:
        lines.append(f"  Error: {eh['condition']} -> \"{eh['message']}\"")
    return "\n".join(lines)


def generate_dev_stories(
    epic: dict[str, Any],
    stories: list[dict[str, Any]],
    client,
    model: str = DEV_STORY_MODEL,
) -> tuple[list[dict[str, Any]], Usage]:
    """Development stories for one epic's user stories. Every story id returned
    is one of the given ones; a user story the model skipped is reported by the
    caller rather than invented here."""
    blocks = [f"EPIC {epic['external_id']}: {epic['title']}"]
    if epic.get("assumptions"):
        blocks.append("Assumptions: " + "; ".join(epic["assumptions"]))
    if epic.get("dependencies"):
        blocks.append("Dependencies: " + "; ".join(epic["dependencies"]))
    blocks.append("\nUSER STORIES")
    blocks.extend(_format_user_story(s) for s in stories)
    request = "\n".join(blocks) + "\n\nPlan the development stories per your instructions."

    def make_request():
        return client.chat.completions.create(
            model=model,
            max_tokens=DEV_STORY_MAX_TOKENS,
            temperature=0,
            messages=[
                {"role": "system", "content": _DEV_STORY_SYSTEM_PROMPT},
                {"role": "user", "content": request},
            ],
            tools=[_DEV_STORY_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_dev_stories"}},
        )

    data, usage = _create_and_parse_tool_call(make_request, "record_dev_stories")
    known = {s["external_id"] for s in stories}
    planned = [d for d in data["dev_stories"] if d["source_story"] in known and d["tasks"]]
    return planned, usage


# ── Tech profile from an uploaded document ──────────────────────────────────

_TECH_PROFILE_SYSTEM_PROMPT = (
    "You read a company's technical document (architecture overview, stack decision, "
    "engineering handbook) and record the technology it specifies for each area. Quote or "
    "closely paraphrase what the document says — names, versions, patterns, rules. If the "
    "document says nothing clear about an area, return an empty string for it: never fill a "
    "gap with your own recommendation. Return via the record_tech_profile tool."
)

_TECH_PROFILE_PARAMETERS = {
    "type": "object",
    "properties": {area: {"type": "string"} for area in TECH_AREAS},
    "required": list(TECH_AREAS),
    "additionalProperties": False,
}

_TECH_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "record_tech_profile",
        "description": "Record what the document specifies for each technical area (empty when it doesn't say).",
        "parameters": _TECH_PROFILE_PARAMETERS,
        "strict": True,
    },
}


def read_tech_profile(document_text: str, client, model: str = TECH_PROFILE_MODEL) -> tuple[dict[str, str], Usage]:
    """{area: text} from a tech-stack document; empty strings where it is silent."""
    area_list = "\n".join(f"- {key}: {label}" for key, label in TECH_AREAS.items())

    def make_request():
        return client.chat.completions.create(
            model=model,
            max_tokens=TECH_PROFILE_MAX_TOKENS,
            temperature=0,
            messages=[
                {"role": "system", "content": _TECH_PROFILE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Areas:\n{area_list}\n\nDocument:\n{document_text}",
                },
            ],
            tools=[_TECH_PROFILE_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_tech_profile"}},
        )

    data, usage = _create_and_parse_tool_call(make_request, "record_tech_profile")
    return {area: (data.get(area) or "").strip() for area in TECH_AREAS}, usage
