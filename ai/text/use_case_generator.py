"""
use_case_generator.py
Reads one approved story and returns the structured parts of a UML use-case
diagram: who the actors are, the story's main use case, the sub-behaviours it
always includes, and the optional/exceptional ones that extend it. The model
returns data, never diagram syntax — backend/app/services/use_case_diagrams.py
turns it into PlantUML, so the diagram text is always valid and every label is
sanitized in one place.

Advisory like every AI output here: it is derived only from the story's own
text (description, acceptance criteria, scenarios, error handling) and must not
invent capabilities the story doesn't describe.
"""

import json
from types import SimpleNamespace
from typing import Any

from config import USE_CASE_MAX_TOKENS, USE_CASE_MODEL

_MAX_ATTEMPTS = 2

SYSTEM_PROMPT = (
    "You are a senior business analyst drawing a UML use-case diagram for ONE user story. "
    "Return only the diagram's structure via the tool; do not write any diagram syntax.\n\n"
    "Rules:\n"
    "- primary_actor: the role in the story's 'As a [role]' (a short noun phrase, e.g. "
    "'Startup', 'Administrator'). If the story has no stated role, use the most sensible "
    "role from the text, else 'User'.\n"
    "- secondary_actors: OTHER people or external systems the story's scenarios or error "
    "handling clearly involve (e.g. 'Investor', 'Email service'). Usually empty. Never repeat "
    "the primary actor. At most 3.\n"
    "- main_use_case: the story's goal as a short verb phrase of at most 6 words "
    "(e.g. 'Edit company profile'), not a sentence and not the whole story title.\n"
    "- includes: behaviours the main use case ALWAYS performs as part of itself "
    "(e.g. 'Validate required fields'). At most 4, short verb phrases.\n"
    "- extends: optional or exceptional behaviours that branch off the main use case "
    "(e.g. 'Show save error', 'Request approval'), usually drawn from the scenarios and error "
    "handling. At most 4, short verb phrases.\n"
    "- Ground everything in the story text. Do not invent capabilities, roles or systems it "
    "does not mention. Prefer fewer, accurate elements over a crowded diagram. Use the "
    "story's own vocabulary."
)

TOOL = {
    "type": "function",
    "function": {
        "name": "record_use_case",
        "description": "Record the structure of this story's use-case diagram.",
        "parameters": {
            "type": "object",
            "properties": {
                "primary_actor": {"type": "string"},
                "secondary_actors": {"type": "array", "items": {"type": "string"}},
                "main_use_case": {"type": "string"},
                "includes": {"type": "array", "items": {"type": "string"}},
                "extends": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["primary_actor", "secondary_actors", "main_use_case", "includes", "extends"],
        },
    },
}


def _story_prompt(story: dict[str, Any], system_name: str) -> str:
    return (
        f"System: {system_name}\n\n"
        "Story (JSON):\n"
        f"{json.dumps(story, indent=2, ensure_ascii=False)}\n\n"
        "Record the use-case diagram structure for this story."
    )


def generate_use_case_spec(story: dict[str, Any], system_name: str, client, model: str = USE_CASE_MODEL):
    """Returns (spec dict, usage). Retries once on a malformed tool response;
    raises ValueError if both attempts are malformed."""
    prompt = _story_prompt(story, system_name)
    prompt_tokens = completion_tokens = 0
    last_error = "no response"
    for _ in range(_MAX_ATTEMPTS):
        response = client.chat.completions.create(
            model=model,
            max_tokens=USE_CASE_MAX_TOKENS,
            temperature=0,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            tools=[TOOL],
            tool_choice={"type": "function", "function": {"name": "record_use_case"}},
        )
        prompt_tokens += response.usage.prompt_tokens
        completion_tokens += response.usage.completion_tokens
        try:
            spec = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
        except (TypeError, IndexError, AttributeError, json.JSONDecodeError) as e:
            last_error = f"malformed tool call ({e})"
            continue
        if (
            isinstance(spec, dict)
            and str(spec.get("primary_actor", "")).strip()
            and str(spec.get("main_use_case", "")).strip()
        ):
            return spec, SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        last_error = "missing primary_actor or main_use_case"
    raise ValueError(f"Use-case generation failed: {last_error}")
