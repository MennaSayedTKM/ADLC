"""
ux_prompt_generator.py
Turns an approved epic and its user stories into a Figma Make prompt — the
UI/UX step that follows requirements. A PM pastes the result into Figma Make
to generate screens; developers later use those screens as their build
reference, so the prompt has to pin down structure, states and behavior, not
just look.

Three modes, chosen by the PM:
  foundation    — new platform: design system tokens, app shell, first flows.
  new_feature   — screens for a feature in a product whose design system
                  already exists; reuses the saved token summary.
  edit_existing — a targeted change to screens that already exist; must say
                  what to keep untouched so Figma doesn't regenerate everything.

Advisory only: nothing here talks to Figma. Same tool-calling pattern as the
other generators in requirements_extractor.py, reusing its retry-on-malformed-
response helper rather than duplicating it.
"""

import sys
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import UX_PROMPT_MAX_TOKENS, UX_PROMPT_MODEL, UX_PROMPT_SOFT_CHAR_LIMIT  # noqa: E402

from .common import Usage  # noqa: E402
from .requirements_extractor import _create_and_parse_tool_call  # noqa: E402

MODES = ("foundation", "new_feature", "edit_existing")

DEFAULT_REFERENCE_BRAND = (
    "Apple Human Interface Guidelines: clarity, deference, depth — generous whitespace, "
    "restrained color, one accent, system-style typography, subtle motion"
)

_SHARED_RULES = """\
You are a principal product designer (10+ years, shipped design systems at scale) writing a \
prompt for Figma Make, an AI tool that generates UI screens from text. Your prompt will be \
pasted in by a project manager, and the screens it produces become the reference developers \
build from — so it must be precise about structure, components, states and behavior.

WRITE THE PROMPT LIKE A DESIGN SPEC, NOT AN ESSAY.
- Telegraphic and dense: token values, component names, lists. No filler, no marketing tone, \
no explaining what good design is. Every sentence must change what Figma generates.
- Credit-efficient: aim for roughly {soft_limit} characters or fewer. Cover the essentials \
completely instead of padding; merge screens that share a layout by describing the shared \
layout once.
- Plain text with simple headings (ALL-CAPS section labels) and hyphen lists. No markdown \
tables, no code fences, no emojis.

GROUND EVERYTHING IN THE STORIES.
- Design only what the given stories, acceptance criteria, scenarios and error handling \
describe. Never add features, roles or screens the stories don't imply. If a needed detail \
is missing, use realistic placeholder content and mark it [placeholder] rather than \
inventing business rules.
- Name every screen so it can be traced back: "Screen: <Name> (S3, S4)" using the story ids \
given. Each acceptance criterion and scenario must be visibly satisfiable on some screen.
- Turn scenarios into states: each Given/When/Then becomes a UI behavior or state on the \
right screen. Turn every error-handling entry into a concrete error state (where it appears, \
what it says — use the given wording verbatim).
- Use the story's own role names for users. Use real field and button labels derived from \
the stories; verb-first button labels ("Save strategy", not "Submit").

DESIGN WITH CRAFT.
- One clear primary action per screen. Consistent 8pt spacing rhythm. A type scale of at most \
5 sizes. Meaningful hierarchy through size and weight before color.
- For every screen list its states: default, empty (with next-step CTA), loading (skeleton \
for lists, inline spinner for actions), error, success/confirmation, and any \
permission-denied state the stories imply.
- Forms: visible labels (placeholder only for format hints), validate on blur, inline errors \
that explain how to fix, disabled-until-valid is forbidden — keep submit clickable.
- Destructive actions name the thing being affected in the confirmation.
- Accessibility: WCAG AA contrast, 44px minimum touch targets, visible keyboard focus ring, \
labels for icon-only buttons, respect reduced motion.
- Responsive: state behavior at desktop (1280), tablet (768) and mobile (375); say what \
collapses or reflows.

END the prompt with a short DO NOT list: no extra screens or features beyond those listed, \
no lorem ipsum, no placeholder brand logos, no decorative gradients or glassmorphism, no \
hardcoded one-off colors outside the tokens.

Return your result via the record_ux_prompt tool."""

_FOUNDATION_MODE = """\
MODE: FOUNDATION — the first prompt for a brand-new platform.
The prompt_text must contain, in this order:
1. PRODUCT CONTEXT — 3 lines: what the product is, primary users (roles from the stories), platform.
2. DESIGN SYSTEM — full tokens, concrete values: color (primary, neutral ramp, semantic \
success/warning/danger/info, surface/background/border/text, with hex for light and dark \
if dark is requested), typography (family, sizes, weights, line-heights), spacing scale, \
corner radius, elevation (border-first, soft shadow only for overlays), motion durations and \
easing, iconography style. Base these on the reference brand and style brief given.
3. COMPONENT LIBRARY — the components these stories need (buttons, inputs, selects, tables, \
cards, tabs, dialogs, toasts, badges, empty states…), each with its variants and states \
(default, hover, focus, pressed, disabled, loading, error).
4. APP SHELL & NAVIGATION — layout, sidebar/top-bar, nav items relevant to these stories, \
breadcrumbs, user menu.
5. SCREENS — the full per-screen spec for this epic's selected stories.
6. FLOWS — the click path for each story from entry point to confirmation.
7. RESPONSIVE & ACCESSIBILITY, then the DO NOT list.
Also fill design_tokens_summary: a COMPACT (under 1,200 characters) recap of the design \
system you just defined — key hex values, font family and scale, spacing/radius, shell layout, \
navigation items, and the component names — so a later prompt for a different feature can \
say "reuse this system" without re-sending the whole thing."""

_NEW_FEATURE_MODE = """\
MODE: NEW FEATURE — the design system and app shell already exist.
Do NOT redefine tokens or the shell. Open the prompt with a REUSE block: "Use the existing \
design system and app shell exactly as they are:" followed by the provided design tokens \
summary, and instruct Figma to reuse existing components and only add new ones where the \
stories require it (name them). Then: the new navigation entry / entry point into the \
existing shell, SCREENS, FLOWS, RESPONSIVE & ACCESSIBILITY, and the DO NOT list (which must \
include: do not change existing screens or tokens).
If no design tokens summary is provided, say in the prompt to infer and match the visual \
language of the existing project files, and keep component styling generic-consistent.
Leave design_tokens_summary as an empty string."""

_EDIT_MODE = """\
MODE: EDIT EXISTING — a targeted change to screens that already exist.
Structure the prompt as an edit instruction, not a fresh design:
1. TARGET — which existing screen(s) to modify (from the story titles and, when provided, \
the description of the current screen).
2. CHANGE — a precise list of additions, modifications and removals, each tied to a story id.
3. KEEP UNCHANGED — explicitly list what must not change: layout regions, tokens, \
navigation, unrelated components. Say "do not regenerate or restyle the rest of the screen".
4. STATES & BEHAVIOR that the change introduces (including error states from the stories).
5. RESPONSIVE & ACCESSIBILITY only for the changed parts, then the DO NOT list.
Use the provided design tokens summary so new elements match. If a description of the \
current screen is provided, anchor every change to elements in it by name/position.
Leave design_tokens_summary as an empty string."""

SYSTEM_PROMPTS = {
    "foundation": f"{_SHARED_RULES}\n\n{_FOUNDATION_MODE}",
    "new_feature": f"{_SHARED_RULES}\n\n{_NEW_FEATURE_MODE}",
    "edit_existing": f"{_SHARED_RULES}\n\n{_EDIT_MODE}",
}

_UX_PROMPT_PARAMETERS = {
    "type": "object",
    "properties": {
        "prompt_text": {"type": "string"},
        "screen_names": {"type": "array", "items": {"type": "string"}},
        "design_tokens_summary": {"type": "string"},
    },
    "required": ["prompt_text", "screen_names", "design_tokens_summary"],
    "additionalProperties": False,
}

_UX_PROMPT_TOOL = {
    "type": "function",
    "function": {
        "name": "record_ux_prompt",
        "description": "Record the finished Figma Make prompt for the given epic and stories.",
        "parameters": _UX_PROMPT_PARAMETERS,
        "strict": True,
    },
}


def _format_story(story: dict[str, Any]) -> str:
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


def _format_style_brief(style_brief: dict[str, Any]) -> str:
    labels = [
        ("reference_brand", "Reference brand / feel"),
        ("primary_color", "Primary brand color"),
        ("tone", "Tone"),
        ("appearance", "Appearance (light/dark)"),
        ("platform", "Platform"),
        ("brand_notes", "Logo / brand notes"),
    ]
    lines = [f"- {label}: {style_brief[key]}" for key, label in labels if style_brief.get(key)]
    return "\n".join(lines) if lines else "- (none given — use the defaults)"


def build_ux_prompt_request(
    mode: str,
    epic: dict[str, Any],
    stories: list[dict[str, Any]],
    style_brief: dict[str, Any],
    design_tokens_summary: Optional[str] = None,
    existing_screen_description: Optional[str] = None,
) -> str:
    parts = [
        f"EPIC {epic['external_id']}: {epic['title']}",
    ]
    if epic.get("assumptions"):
        parts.append("Assumptions: " + "; ".join(epic["assumptions"]))
    if epic.get("dependencies"):
        parts.append("Dependencies: " + "; ".join(epic["dependencies"]))

    parts.append("\nSELECTED USER STORIES (design only these):\n" + "\n\n".join(_format_story(s) for s in stories))

    brief = dict(style_brief)
    if not brief.get("reference_brand"):
        brief["reference_brand"] = DEFAULT_REFERENCE_BRAND
    parts.append("\nSTYLE BRIEF FROM THE PM:\n" + _format_style_brief(brief))

    if mode != "foundation":
        parts.append(
            "\nEXISTING DESIGN TOKENS SUMMARY:\n"
            + (design_tokens_summary or "(none saved — see the mode instructions for this case)")
        )
    if mode == "edit_existing" and existing_screen_description:
        parts.append("\nDESCRIPTION OF THE CURRENT SCREEN (from a screenshot):\n" + existing_screen_description)

    parts.append("\nWrite the Figma Make prompt now, per your instructions.")
    return "\n".join(parts)


def generate_ux_prompt(
    mode: str,
    epic: dict[str, Any],
    stories: list[dict[str, Any]],
    style_brief: dict[str, Any],
    client,
    model: str = UX_PROMPT_MODEL,
    design_tokens_summary: Optional[str] = None,
    existing_screen_description: Optional[str] = None,
) -> tuple[dict[str, Any], Usage]:
    """
    Returns ({"prompt_text", "screen_names", "design_tokens_summary"}, usage).
    epic/stories are plain dicts (external_id, title/text mapped to "title", …)
    so this module stays free of any DB model dependency.
    """
    if mode not in MODES:
        raise ValueError(f"Unknown mode {mode!r} — expected one of {MODES}")
    if not stories:
        raise ValueError("Select at least one story to generate a prompt for.")

    system_prompt = SYSTEM_PROMPTS[mode].format(soft_limit=UX_PROMPT_SOFT_CHAR_LIMIT)
    request = build_ux_prompt_request(
        mode, epic, stories, style_brief, design_tokens_summary, existing_screen_description
    )

    def make_request():
        return client.chat.completions.create(
            model=model,
            max_tokens=UX_PROMPT_MAX_TOKENS,
            temperature=0.4,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request},
            ],
            tools=[_UX_PROMPT_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_ux_prompt"}},
        )

    data, usage = _create_and_parse_tool_call(make_request, "record_ux_prompt")
    if not data["prompt_text"].strip():
        raise ValueError("Model returned an empty prompt.")
    return data, usage
