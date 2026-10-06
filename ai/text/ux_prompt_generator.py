"""
ux_prompt_generator.py
Turns approved requirements into Figma Make prompts — the UI/UX step that
follows requirements. A PM pastes each prompt into Figma Make; the screens it
produces become the reference developers build from, so prompts pin down
structure, states and behavior, not just look.

Think of it as building with Lego:

  foundation    — the PLATFORM BLUEPRINT. Not tied to any epic: the platform's
                  vision, design system, app shell and navigation, with an empty
                  placeholder slot for every planned feature. The baseplate.
  new_feature   — one epic's stories, designed to snap into its placeholder slot.
  edit_existing — a targeted change to screens that already exist.

Figma Make only knows what is in the prompt and in its own project, so every
feature/edit prompt carries a CONTEXT PACK (design tokens, navigation, screens
already designed, components to reuse, related features) built by
backend/app/services/ux_prompts.py. That is how features stay consistent
without the agent ever seeing the whole picture.

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

GROUND EVERYTHING IN THE INPUT.
- Design only what the given vision, stories, acceptance criteria, scenarios and error \
handling describe. Never add features, roles or screens they don't imply. If a needed detail \
is missing, use realistic placeholder content and mark it [placeholder] rather than \
inventing business rules.
- Use the story's own role names for users. Use real field and button labels derived from \
the stories; verb-first button labels ("Save strategy", not "Submit").

DESIGN WITH CRAFT.
- One clear primary action per screen. Consistent 8pt spacing rhythm. A type scale of at most \
5 sizes. Meaningful hierarchy through size and weight before color.
- Accessibility: WCAG AA contrast, 44px minimum touch targets, visible keyboard focus ring, \
labels for icon-only buttons, respect reduced motion.
- Responsive: state behavior at desktop (1280), tablet (768) and mobile (375); say what \
collapses or reflows.

REFERENCE STYLES. When the input includes REFERENCE STYLES extracted from real websites, \
treat them as the visual source of truth: use their actual palette, fonts and radii (name the \
hex values and families you adopt) rather than inventing your own. Where several references \
conflict, follow the one the PM labelled as the overall feel and borrow only what each note \
says. Adapt, don't clone — never reproduce another brand's logo or copy.

Return your result via the record_ux_prompt tool."""

_FEATURE_RULES = """\
FEATURE AND SCREEN RULES (feature and edit prompts).
- Name every screen so it can be traced back: "Screen: <Name> (S3, S4)" using the story ids \
given. Each acceptance criterion and scenario must be visibly satisfiable on some screen.
- Turn scenarios into states: each Given/When/Then becomes a UI behavior or state on the \
right screen. Turn every error-handling entry into a concrete error state (where it appears, \
what it says — use the given wording verbatim).
- For every screen list its states: default, empty (with next-step CTA), loading (skeleton \
for lists, inline spinner for actions), error, success/confirmation, and any \
permission-denied state the stories imply.
- Forms: visible labels (placeholder only for format hints), validate on blur, inline errors \
that explain how to fix, never disable submit until valid.
- Destructive actions name the thing being affected in the confirmation.

CONSISTENCY WITH THE REST OF THE PLATFORM (the most important rule).
You are adding one piece to a platform that already exists in this Figma Make project. A \
PLATFORM CONTEXT block is provided in the input: design tokens, navigation, screens already \
designed, components to reuse, and related features.
- Open the prompt with a CONTEXT section restating it in at most ~1,200 characters, telling \
Figma to reuse the existing design system, shell and components exactly.
- Use only existing tokens and components; add a new component only if the stories require \
it, and name it so it can be added to the library.
- Every screen needs a route under the feature's base route, and links to related features \
must point at the real screens/routes listed in the context.
- Under INTEGRATION list every touchpoint with a related feature: what the user can jump to, \
what data is shown from it or sent to it, using the screen names given.
- Do not alter any existing screen, token, or navigation entry except activating this \
feature's placeholder slot.

END the prompt with a short DO NOT list: no extra screens or features beyond those listed, \
no lorem ipsum, no placeholder brand logos, no decorative gradients or glassmorphism, no \
hardcoded one-off colors outside the tokens, and (feature/edit) nothing that changes existing \
screens or tokens."""

_FOUNDATION_MODE = """\
MODE: PLATFORM BLUEPRINT — the base every later feature is added to.
This prompt is about the WHOLE platform, not any one epic. Think of a Lego baseplate: build \
the empty, finished-looking building — design system, app shell, navigation — with a clearly \
marked slot for every planned feature, and nothing inside the slots yet.

The prompt_text must contain, in this order:
1. VISION & PURPOSE — 3-4 lines from the PM's vision: what the platform is, why it exists, \
the feel it should have.
2. USERS & ROLES — who uses it (from the vision and the planned features), and how their \
needs shape the shell (e.g. a dense admin tool vs. a calm executive dashboard).
3. DESIGN SYSTEM — full tokens with concrete values, built from the REFERENCE STYLES and \
style brief: color (primary, neutral ramp, semantic success/warning/danger/info, \
surface/background/border/text; hex for light and dark if dark is requested), typography \
(family, sizes, weights, line-heights), spacing scale, corner radius, elevation \
(border-first, soft shadow for overlays), motion durations and easing, iconography style.
4. COMPONENT LIBRARY — the components the planned features will need (buttons, inputs, \
selects, tables, cards, tabs, dialogs, toasts, badges, empty states, page header, filter \
bar…), each with variants and states (default, hover, focus, pressed, disabled, loading, error).
5. APP SHELL & NAVIGATION — layout, sidebar/top-bar, user menu, breadcrumbs, global search \
only if implied. Navigation has ONE ITEM PER PLANNED FEATURE, in the order given, each \
routing to its placeholder.
6. PLACEHOLDER PAGE — one reusable page template (page header with feature name and \
breadcrumb, a one-line description, an empty-state panel "This feature is being designed") \
and the list of placeholders: label · route · one-line purpose. These are NOT designed \
screens; do not invent content for them.
7. PLATFORM-LEVEL SCREENS — only screens the platform itself needs and the vision implies \
(e.g. home/dashboard, sign-in, profile/settings). Skip any not implied.
8. EXTENSION RULES — how features are added later: use only these tokens and components, \
activate the nav slot, route naming "/<feature>/<screen>", screen naming \
"<Feature> / <Screen>", states required on every screen.
Then RESPONSIVE & ACCESSIBILITY and the DO NOT list (no feature screens, no content inside \
placeholders).

Also fill:
- design_tokens_summary: a COMPACT (under 1,200 characters) recap of the design system — key \
hex values, font family and scale, spacing/radius, shell layout, and the component names.
- nav_items: one entry per planned feature given in the input: epic_external_id exactly as \
given, a short label, and a kebab-case route starting with "/".
- component_names: the component library names, as a short list.
- screens: the platform-level screens from section 7 (name, route, purpose); empty list if none."""

_NEW_FEATURE_MODE = """\
MODE: NEW FEATURE — one epic, snapped into the platform's placeholder slot.
Structure: CONTEXT (restated from the PLATFORM CONTEXT, per the rules above) · PLACEHOLDER \
TO REPLACE (the nav item and route of this feature's slot) · SCREENS · INTEGRATION · FLOWS \
(the click path for each story, entry point to confirmation) · RESPONSIVE & ACCESSIBILITY · \
DO NOT.
Do NOT redefine tokens, shell or components. Leave design_tokens_summary as an empty string, \
nav_items and component_names empty lists. screens lists every screen you designed with its \
route under the feature's base route and a one-line purpose."""

_EDIT_MODE = """\
MODE: EDIT EXISTING — a targeted change to screens that already exist.
Structure the prompt as an edit instruction, not a fresh design:
1. CONTEXT — brief, per the rules above.
2. TARGET — which existing screen(s) to modify, by the exact names/routes in the screen \
registry and, when provided, the description of the current screen.
3. CHANGE — a precise list of additions, modifications and removals, each tied to a story id.
4. KEEP UNCHANGED — explicitly list what must not change: layout regions, tokens, \
navigation, unrelated components. Say "do not regenerate or restyle the rest of the screen".
5. STATES & BEHAVIOR the change introduces (including error states from the stories), then \
INTEGRATION if related features are affected, RESPONSIVE & ACCESSIBILITY for the changed \
parts only, and the DO NOT list.
If a description of the current screen is provided, anchor every change to elements in it by \
name/position. Leave design_tokens_summary as an empty string, nav_items and component_names \
empty lists; screens lists only screens that are NEW (empty if the edit adds none)."""

SYSTEM_PROMPTS = {
    "foundation": f"{_SHARED_RULES}\n\n{_FOUNDATION_MODE}",
    "new_feature": f"{_SHARED_RULES}\n\n{_FEATURE_RULES}\n\n{_NEW_FEATURE_MODE}",
    "edit_existing": f"{_SHARED_RULES}\n\n{_FEATURE_RULES}\n\n{_EDIT_MODE}",
}

_SCREEN_ITEM = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "route": {"type": "string"}, "purpose": {"type": "string"}},
    "required": ["name", "route", "purpose"],
    "additionalProperties": False,
}

_UX_PROMPT_PARAMETERS = {
    "type": "object",
    "properties": {
        "prompt_text": {"type": "string"},
        "screens": {"type": "array", "items": _SCREEN_ITEM},
        "design_tokens_summary": {"type": "string"},
        "nav_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "epic_external_id": {"type": "string"},
                    "label": {"type": "string"},
                    "route": {"type": "string"},
                },
                "required": ["epic_external_id", "label", "route"],
                "additionalProperties": False,
            },
        },
        "component_names": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["prompt_text", "screens", "design_tokens_summary", "nav_items", "component_names"],
    "additionalProperties": False,
}

_UX_PROMPT_TOOL = {
    "type": "function",
    "function": {
        "name": "record_ux_prompt",
        "description": "Record the finished Figma Make prompt and its structured outputs.",
        "parameters": _UX_PROMPT_PARAMETERS,
        "strict": True,
    },
}


# ── Input formatting ─────────────────────────────────────────────────────────

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


def format_reference_styles(references: list[dict[str, Any]]) -> str:
    """Compact text for the extracted style tags of each reference site."""
    blocks = []
    for ref in references or []:
        tags = ref.get("style_tags") or {}
        title = ref.get("title") or ref.get("url", "")
        lines = [f"- {title} ({ref.get('url', '')})" + (f" — PM note: {ref['note']}" if ref.get("note") else "")]
        if tags.get("palette"):
            lines.append("  Colors: " + ", ".join(f"{p['hex']} ({p['kind']})" for p in tags["palette"][:8]))
        guesses = [
            f"{label} {tags[key]}"
            for key, label in (("accent_guess", "accent"), ("background_guess", "background"), ("text_guess", "text"))
            if tags.get(key)
        ]
        if guesses:
            lines.append("  Likely roles: " + ", ".join(guesses))
        fonts = list(tags.get("fonts") or []) + [f for f in tags.get("google_fonts") or [] if f not in (tags.get("fonts") or [])]
        if fonts:
            lines.append("  Fonts: " + ", ".join(fonts[:5]))
        if tags.get("font_sizes_px"):
            lines.append("  Font sizes (px): " + ", ".join(f"{s:g}" for s in tags["font_sizes_px"]))
        if tags.get("radii"):
            lines.append("  Corner radii: " + ", ".join(tags["radii"]))
        if tags.get("shadows"):
            lines.append("  Shadows: " + " | ".join(tags["shadows"]))
        if tags.get("css_variables"):
            lines.append("  Design tokens: " + "; ".join(f"--{k}: {v}" for k, v in list(tags["css_variables"].items())[:12]))
        if ref.get("theme_color"):
            lines.append(f"  Theme color: {ref['theme_color']}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _format_planned_features(epics: list[dict[str, Any]]) -> str:
    lines = []
    for e in epics:
        lines.append(f"{e['external_id']}: {e['title']}")
        for s in e.get("stories", []):
            lines.append(f"    - {s['external_id']} {s['title']}")
    return "\n".join(lines)


def build_ux_prompt_request(
    mode: str,
    style_brief: dict[str, Any],
    epic: Optional[dict[str, Any]] = None,
    stories: Optional[list[dict[str, Any]]] = None,
    planned_features: Optional[list[dict[str, Any]]] = None,
    context_pack: Optional[str] = None,
    existing_screen_description: Optional[str] = None,
) -> str:
    parts: list[str] = []

    if mode == "foundation":
        parts.append("PLATFORM VISION (from the PM):\n" + (style_brief.get("vision") or "(not provided — infer a modest, sensible vision from the planned features and say so in section 1)"))
        if style_brief.get("target_users"):
            parts.append("\nTARGET USERS (from the PM):\n" + style_brief["target_users"])
        parts.append(
            "\nPLANNED FEATURES — one navigation slot each, in this order:\n"
            + _format_planned_features(planned_features or [])
        )
    else:
        parts.append(f"EPIC {epic['external_id']}: {epic['title']}")
        if epic.get("assumptions"):
            parts.append("Assumptions: " + "; ".join(epic["assumptions"]))
        if epic.get("dependencies"):
            parts.append("Dependencies: " + "; ".join(epic["dependencies"]))
        parts.append("\nSELECTED USER STORIES (design only these):\n" + "\n\n".join(_format_story(s) for s in stories or []))
        parts.append("\nPLATFORM CONTEXT (already built in this Figma Make project):\n" + (context_pack or "(none available — infer and match the existing project's visual language)"))

    brief = dict(style_brief)
    if not brief.get("reference_brand") and not brief.get("reference_styles"):
        brief["reference_brand"] = DEFAULT_REFERENCE_BRAND
    parts.append("\nSTYLE BRIEF FROM THE PM:\n" + _format_style_brief(brief))

    if mode == "foundation" and style_brief.get("reference_styles"):
        parts.append("\nREFERENCE STYLES (extracted from real websites):\n" + format_reference_styles(style_brief["reference_styles"]))

    if mode == "edit_existing" and existing_screen_description:
        parts.append("\nDESCRIPTION OF THE CURRENT SCREEN (from a screenshot):\n" + existing_screen_description)

    parts.append("\nWrite the Figma Make prompt now, per your instructions.")
    return "\n".join(parts)


def generate_ux_prompt(
    mode: str,
    style_brief: dict[str, Any],
    client,
    model: str = UX_PROMPT_MODEL,
    epic: Optional[dict[str, Any]] = None,
    stories: Optional[list[dict[str, Any]]] = None,
    planned_features: Optional[list[dict[str, Any]]] = None,
    context_pack: Optional[str] = None,
    existing_screen_description: Optional[str] = None,
) -> tuple[dict[str, Any], Usage]:
    """
    Returns ({"prompt_text", "screens", "design_tokens_summary", "nav_items",
    "component_names"}, usage). epic/stories/planned_features are plain dicts
    (external_id, title, …) so this module stays free of any DB dependency.
    """
    if mode not in MODES:
        raise ValueError(f"Unknown mode {mode!r} — expected one of {MODES}")
    if mode == "foundation":
        if not planned_features:
            raise ValueError("The platform blueprint needs at least one planned feature (epic).")
    else:
        if epic is None or not stories:
            raise ValueError("Select an epic and at least one of its stories.")

    system_prompt = SYSTEM_PROMPTS[mode].format(soft_limit=UX_PROMPT_SOFT_CHAR_LIMIT)
    request = build_ux_prompt_request(
        mode, style_brief, epic, stories, planned_features, context_pack, existing_screen_description
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


# ── Feature relationships ────────────────────────────────────────────────────

_RELATIONSHIPS_SYSTEM_PROMPT = (
    "You are a senior product designer and business analyst mapping how the features of one "
    "software platform relate, so they can be designed in a sensible order and linked "
    "consistently. You are given every epic with its stories (and any dependencies the "
    "requirements document stated).\n\n"
    "For each epic, report:\n"
    "- depends_on: epic ids that must exist first because this epic uses their data, screens "
    "or configuration (e.g. 'Reporting' depends on the epic that creates the records being "
    "reported). Only real dependencies evidenced by the stories or the stated dependencies — "
    "never guess, and never list an epic as depending on itself.\n"
    "- integrates: other epics this one touches at the UI level without strictly depending on "
    "them (shared entities, links, notifications, shared lists). Each entry names the other "
    "epic and says in one short clause what is shared or linked (e.g. 'objective picker reuses "
    "the strategy hierarchy list').\n\n"
    "Use the epic ids exactly as given. Leave lists empty when there is no evidence — an "
    "empty list is a correct answer. Return via the record_feature_relationships tool."
)

_RELATIONSHIPS_PARAMETERS = {
    "type": "object",
    "properties": {
        "features": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "epic_external_id": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "integrates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"with_epic": {"type": "string"}, "how": {"type": "string"}},
                            "required": ["with_epic", "how"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["epic_external_id", "depends_on", "integrates"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["features"],
    "additionalProperties": False,
}

_RELATIONSHIPS_TOOL = {
    "type": "function",
    "function": {
        "name": "record_feature_relationships",
        "description": "Record the dependencies and UI touchpoints between the epics.",
        "parameters": _RELATIONSHIPS_PARAMETERS,
        "strict": True,
    },
}


def analyze_feature_relationships(
    epics: list[dict[str, Any]], client, model: str = UX_PROMPT_MODEL
) -> tuple[list[dict[str, Any]], Usage]:
    """Returns (features, usage), features = [{epic_external_id, depends_on, integrates}]."""
    blocks = []
    for e in epics:
        lines = [f"{e['external_id']}: {e['title']}"]
        if e.get("dependencies"):
            lines.append("  Stated dependencies: " + "; ".join(e["dependencies"]))
        for s in e.get("stories", []):
            lines.append(f"  {s['external_id']}: {s['title']}" + (f" — {s['description']}" if s.get("description") else ""))
        blocks.append("\n".join(lines))
    request = "Here are the platform's epics and stories:\n\n" + "\n\n".join(blocks) + "\n\nMap the relationships per your instructions."

    def make_request():
        return client.chat.completions.create(
            model=model,
            max_tokens=UX_PROMPT_MAX_TOKENS,
            temperature=0,
            messages=[
                {"role": "system", "content": _RELATIONSHIPS_SYSTEM_PROMPT},
                {"role": "user", "content": request},
            ],
            tools=[_RELATIONSHIPS_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_feature_relationships"}},
        )

    data, usage = _create_and_parse_tool_call(make_request, "record_feature_relationships")
    return data["features"], usage


# ── Vision drafting ──────────────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = (
    "You are a senior product strategist. From the epics and stories of an approved "
    "requirements document, write a short product vision a designer can build a platform "
    "foundation from.\n\n"
    "vision: 3-5 sentences — what the platform is, the problem it solves, and the feel it "
    "should have (calm, dense, executive, playful…) only where the stories hint at it. "
    "target_users: one short line naming the user roles the stories mention.\n\n"
    "Ground it in the stories; do not invent products, customers or features. Plain language, "
    "no hype. Return via the record_vision tool."
)

_VISION_TOOL = {
    "type": "function",
    "function": {
        "name": "record_vision",
        "description": "Record the drafted product vision and target users.",
        "parameters": {
            "type": "object",
            "properties": {"vision": {"type": "string"}, "target_users": {"type": "string"}},
            "required": ["vision", "target_users"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def draft_vision(epics: list[dict[str, Any]], client, model: str = UX_PROMPT_MODEL) -> tuple[dict[str, str], Usage]:
    request = "Here are the platform's epics and stories:\n\n" + _format_planned_features(epics) + "\n\nDraft the vision per your instructions."

    def make_request():
        return client.chat.completions.create(
            model=model,
            max_tokens=UX_PROMPT_MAX_TOKENS,
            temperature=0.3,
            messages=[
                {"role": "system", "content": _VISION_SYSTEM_PROMPT},
                {"role": "user", "content": request},
            ],
            tools=[_VISION_TOOL],
            tool_choice={"type": "function", "function": {"name": "record_vision"}},
        )

    data, usage = _create_and_parse_tool_call(make_request, "record_vision")
    return {"vision": data["vision"].strip(), "target_users": data["target_users"].strip()}, usage
