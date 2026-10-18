"""
coding_prompt_generator.py
Writes the coding prompt for one technical task (a Jira Sub-task): a complete,
self-contained brief a developer or a coding agent can implement from, in the
shape the team's Jira sub-tasks already use (objective, numbered implementation
tasks as checklists, acceptance criteria, tests, notes).

Runs on Claude (coding_prompt_model in config.yaml) through Amazon Bedrock in
the EU region, using the Anthropic SDK's Bedrock client — the one model call in
this codebase that isn't OpenAI, chosen because these prompts are long technical
specifications where the strongest coding model pays off.

The company's tech stack is followed exactly where it is specified. For an area
the task touches that isn't specified, the prompt recommends one option, names
alternatives with their trade-offs, and is flagged (tech_decision_needed) so the
Jira sub-task gets a label and the team confirms the choice.
"""

import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import CODING_PROMPT_EFFORT, CODING_PROMPT_MAX_TOKENS, CODING_PROMPT_MODEL  # noqa: E402

from .common import Usage  # noqa: E402
from .dev_story_generator import TECH_AREAS  # noqa: E402

SYSTEM_PROMPT = """You are a principal software engineer writing the technical sub-task for one piece of a \
development story. A developer or a coding agent will implement it from your text alone, so it must be \
complete, specific and self-contained.

Write the prompt in Markdown with these sections, in this order:

## Objective
What this task builds and why, in 2-4 sentences tied to the user story.

## Context
What it belongs to (epic, user story, development story), what the other tasks of the same story cover, \
what it depends on and what already exists (screens, earlier stories). Name the interfaces it shares with \
sibling tasks — endpoint contracts, events, data shapes — so the pieces fit together.

## Technology
One line per technical area this task touches, written as `- <Area> [<key>]: ...` with the area's key from \
the tech stack list (e.g. `- Database and storage [database]: ...`). Where the company's stack specifies the \
area, state it and use it exactly. Where it doesn't, write **Decision needed**, give your recommended option \
for this project (consistent with the rest of the stack), then 1-2 alternatives, each with a one-line trade-off.

## Technical Implementation Tasks
Numbered sub-sections, each a list of `- [ ]` checklist items. Be concrete: data structures and fields, \
endpoints (method, path, request and response shape, status codes), validation rules, UI components and \
their states, permissions by role, audit logging, error handling, performance considerations. Write the \
steps for the recommended option where a decision is needed.

## Acceptance Criteria
`- [ ]` items a reviewer can test, covering the user story's criteria that this task delivers.

## Tests
The unit, integration and end-to-end checks expected, naming the cases.

## Notes
Security, privacy, performance, error handling and anything explicitly out of scope for this task.

Rules:
- Stay inside the user story and development story. Don't add features or business rules; where a detail \
the code needs is missing, state the assumption you made and mark it to be confirmed.
- Follow the company's standards when they are given.
- Cover only this task's scope; the sibling tasks cover theirs.
- Only raise a technology decision for an area this task actually touches.
- No filler and no generic advice: every line should change what gets built or checked.

Reply with the Markdown prompt only: no preamble, no closing remarks, no code fence around it."""

_FENCE = re.compile(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", re.DOTALL)
_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_AREA_KEY = re.compile(r"\[([a-z_]+)\]")


class CodingPromptError(Exception):
    """The model declined or returned something unusable; the message says which."""


def build_request(context: dict[str, Any]) -> str:
    """The user message: everything the model needs about this one task. Kept as
    labelled plain-text sections so the prompt is easy to read in logs and tests."""
    lines: list[str] = [f"PROJECT: {context['project_name']}"]
    if context.get("vision"):
        lines.append(f"Platform vision: {context['vision']}")

    lines.append("\nCOMPANY TECH STACK (per area; 'not specified' means you recommend)")
    areas = context.get("tech_areas") or {}
    for key, label in TECH_AREAS.items():
        value = (areas.get(key) or "").strip()
        lines.append(f"- {label} [{key}]: {value or 'not specified'}")
    if context.get("tech_document_excerpt"):
        lines.append("\nFrom the company's technical document:\n" + context["tech_document_excerpt"])

    if context.get("standards"):
        lines.append("\nCOMPANY STANDARDS")
        lines.extend(f"- {s['title']}: {s['text']}" for s in context["standards"])

    epic = context["epic"]
    lines.append(f"\nEPIC {epic['external_id']}: {epic['title']}")
    if epic.get("assumptions"):
        lines.append("Assumptions: " + "; ".join(epic["assumptions"]))
    if epic.get("dependencies"):
        lines.append("Dependencies: " + "; ".join(epic["dependencies"]))

    lines.append("\nUSER STORY\n" + context["user_story_text"])

    dev = context["dev_story"]
    lines.append(f"\nDEVELOPMENT STORY: {dev['title']}\n{dev['description']}")
    if dev.get("acceptance_criteria"):
        lines.append("Acceptance criteria:")
        lines.extend(f"- {c}" for c in dev["acceptance_criteria"])

    task = context["task"]
    lines.append(f"\nTHIS TASK ({task['area']}): {task['title']}\n{task['summary']}")

    if context.get("sibling_tasks"):
        lines.append("\nOTHER TASKS OF THE SAME STORY (not this task's scope)")
        lines.extend(f"- ({t['area']}) {t['title']}: {t['summary']}" for t in context["sibling_tasks"])
    if context.get("story_dependencies"):
        lines.append("\nSTORY DEPENDENCIES")
        lines.extend(f"- {d}" for d in context["story_dependencies"])
    if context.get("screens"):
        lines.append("\nUI SCREENS DESIGNED FOR THIS EPIC")
        lines.extend(f"- {s}" for s in context["screens"])

    lines.append("\nWrite the coding prompt for THIS TASK per your instructions.")
    return "\n".join(lines)


def technology_decisions(markdown: str) -> list[str]:
    """The area keys whose line in the Technology section says Decision needed, in
    order. A decision line without a recognisable key still counts, as "" (a
    decision is needed; the area just isn't named)."""
    headings = list(_SECTION.finditer(markdown))
    for i, heading in enumerate(headings):
        if heading.group(1).strip().lower() != "technology":
            continue
        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown)
        found: list[str] = []
        for line in markdown[heading.end():end].splitlines():
            if "decision needed" not in line.lower():
                continue
            keys = [k for k in _AREA_KEY.findall(line) if k in TECH_AREAS]
            found.extend(keys or [""])
        return list(dict.fromkeys(found))
    return []


def generate_coding_prompt(
    context: dict[str, Any], client, model: str = CODING_PROMPT_MODEL
) -> tuple[dict[str, Any], Usage]:
    """({prompt_markdown, tech_decision_needed, decision_areas}, usage).

    Adaptive thinking is asked for explicitly (Opus 4.8 runs without it
    otherwise; on Opus 5.5 it is the default either way) and effort is set
    explicitly because its default differs between models. The answer is the
    Markdown itself: not every Bedrock endpoint offers structured outputs and
    newer models don't take a forced tool choice, so the decision flags are
    read from the Technology section rather than returned alongside. Streamed,
    because a long specification can outlast a plain request's timeout."""
    with client.messages.stream(
        model=model,
        max_tokens=CODING_PROMPT_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_request(context)}],
        thinking={"type": "adaptive"},
        output_config={"effort": CODING_PROMPT_EFFORT},
    ) as stream:
        response = stream.get_final_message()

    usage = Usage(prompt_tokens=response.usage.input_tokens, completion_tokens=response.usage.output_tokens)
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None) if response.stop_details else None
        raise CodingPromptError(f"The model declined to write this prompt ({category or 'no category given'}).")
    if response.stop_reason == "max_tokens":
        raise CodingPromptError("The prompt was cut off at the output limit; try again or split the task.")

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    if not text:
        raise CodingPromptError("The model returned no prompt text; try again.")
    decisions = technology_decisions(text)
    return {
        "prompt_markdown": text,
        "tech_decision_needed": bool(decisions),
        "decision_areas": [a for a in decisions if a],
    }, usage
