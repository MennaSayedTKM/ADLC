"""
alignment_checker.py
Per-screen design/requirements alignment check — modeled on the same
GPT-4o vision pattern as requirements_extractor.py: one call per screen,
comparing the screen image against the approved requirement stories, and
parsing a strict JSON response.

Each call sends the *other* screens in the same design upload as low-detail
context thumbnails alongside the full-detail focus screen (same low/high
detail cost pattern the ported answer.py reranker uses). Without this, a
requirement satisfied on one screen (e.g. "create node" living on Strategy
Hierarchy) gets wrongly flagged as missing on every other screen (e.g.
Overview) that has no way of knowing it's covered elsewhere — this is one
call whose *verdict* is still about a single screen, not a merged check
across the whole set, so it stays "one call per screen" per the brief.

Each finding can also include a bounding_box on the FOCUS screen, in the same
percentage convention (0=top/left, 100=bottom/right) as the ported answer.py's
_locate_and_crop — reused here for consistency, though this asks the model to
report the region directly rather than doing a second locate call, since the
model already has the finding's context in this same response.

Approved stories are passed inline in the prompt (not retrieved via
search.py) — see ALIGNMENT_MAX_STORIES_INLINE in config.yaml for why: at
phase-1 scale (one PM, one designer, low volume) this is simpler and more
reliable than visual-similarity retrieval, which doesn't map well onto
"textually relevant requirement" anyway (the shared FAISS index embeds by
visual appearance, and a wireframe looks nothing like a requirements PDF
page). If a project ever has more approved stories than the configured
threshold, this raises instead of silently truncating the context.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from .common import image_to_data_url, parse_json_object

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import (  # noqa: E402
    ALIGNMENT_IMAGE_DETAIL,
    ALIGNMENT_MAX_STORIES_INLINE,
    ALIGNMENT_MODEL,
)

SYSTEM_PROMPT = (
    "You are a meticulous product designer reviewing a screen mockup against approved "
    "requirements. You never invent a single overall score — alignment is categorical, "
    "and every issue you raise must cite the specific requirement it concerns."
)


@dataclass
class ApprovedStory:
    external_id: str
    text: str
    acceptance_criteria: list[str]


@dataclass
class PlatformContext:
    """What the design is supposed to be for, so a screen from another product
    (different name, branding or domain) can be recognised as such."""

    name: str
    vision: str = ""


# Confirmed live: nine sign-in/strategy screens from an unrelated product were
# checked against a startup-support platform's stories and seven came back
# "aligned". The old rules only raised findings for requirements a screen is
# related to and called a screen aligned when every *relevant* requirement was
# met, so a screen relevant to nothing was vacuously aligned. The model now
# names the stories the screen implements, and code enforces the outcome when
# it names none (see _enforce_traceability).
UNTRACED_SCREEN_ISSUE = "This screen doesn't correspond to any approved requirement."
UNTRACED_SCREEN_RECOMMENDATION = (
    "Check that the screen belongs to this project. If it does, add the requirement it "
    "implements to the approved stories before treating the design as complete."
)


def _build_prompt(
    stories: list[ApprovedStory],
    has_context_screens: bool,
    platform: Optional[PlatformContext] = None,
) -> str:
    lines = []
    for s in stories:
        ac = "; ".join(s.acceptance_criteria) if s.acceptance_criteria else "(none stated)"
        lines.append(f"- [{s.external_id}] {s.text}\n  Acceptance criteria: {ac}")
    requirements_block = "\n".join(lines) if lines else "(no approved stories)"

    context_note = (
        "You will also be shown low-resolution thumbnails of every other screen in the same "
        "design export, for context only — do not evaluate or raise findings against those "
        "screens directly; they're here so you know what else exists in the flow.\n\n"
        if has_context_screens
        else ""
    )

    platform_note = ""
    if platform is not None:
        platform_note = f"This design is for the platform \"{platform.name}\"."
        if platform.vision:
            platform_note += f" Its purpose: {platform.vision}"
        platform_note += "\n\n"

    return (
        "You will be shown one FOCUS screen from a design export, in detail.\n"
        f"{context_note}"
        f"{platform_note}"
        "Approved requirement stories for this project:\n"
        f"{requirements_block}\n\n"
        "Compare the FOCUS screen against these requirements and return strict JSON with "
        "this exact shape:\n"
        "{\n"
        '  "status": "aligned | partial | misaligned",\n'
        '  "related_requirement_ids": ["S1", ...],\n'
        '  "findings": [\n'
        '    {"requirement_id": "S1", "issue": "...", "recommendation": "...",\n'
        '     "bounding_box": {"top": <n>, "left": <n>, "bottom": <n>, "right": <n>} or null}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- status and findings are about the FOCUS screen specifically, not the design as a "
        "whole.\n"
        "- related_requirement_ids lists the bracketed ids of the approved stories the FOCUS "
        "screen implements or is clearly meant to implement. A generic element alone (a "
        "sign-in form, a navigation bar) does not make a screen related to a story.\n"
        "- If the FOCUS screen implements none of the approved stories — for example it shows "
        "a different product's name, branding or subject matter, or functionality these "
        "requirements don't describe — return an empty related_requirement_ids, status "
        "\"misaligned\", and one finding with requirement_id null that says what the screen "
        "shows and that it doesn't trace to any approved requirement. Such a screen is never "
        "\"aligned\".\n"
        "- status: \"aligned\" if the focus screen satisfies the requirements it's relevant "
        "to, \"partial\" if it's close but missing or diverging on some points, "
        "\"misaligned\" if it substantially fails to implement what's required.\n"
        "- Every finding's requirement_id must be one of the bracketed ids above, except the "
        "single untraceable-screen finding described above, whose requirement_id is null.\n"
        "- Do not raise a finding for a requirement the focus screen isn't related to.\n"
        "- A requirement is NOT missing on the focus screen if you can see it's clearly "
        "satisfied on one of the other screens shown for context — that's expected in a "
        "multi-screen flow, not a gap. Only flag it here if it isn't satisfied anywhere "
        "you can see, or if the focus screen itself implements it incorrectly.\n"
        "- If the focus screen fully satisfies every relevant requirement (whether directly "
        "or because it's clearly handled elsewhere in the flow), return an empty findings "
        "array and status \"aligned\".\n"
        "- bounding_box locates the specific region of the FOCUS screen (not a context "
        "thumbnail) the finding is about, as percentages of the FOCUS screen's dimensions "
        "(0=top/left, 100=bottom/right). Include it whenever the issue concerns something "
        "visibly present but wrong (e.g. a mislabeled or misplaced element). Set it to null "
        "when there's nothing to point at — e.g. the issue is that something is entirely "
        "absent from the screen.\n"
        "- Recommendations must be specific and actionable — describe what to change, "
        "not just what's wrong.\n"
        "- Return ONLY the JSON object — no markdown fences, no commentary before or after."
    )


def check_alignment(
    screen_image: Image.Image,
    approved_stories: list[ApprovedStory],
    client,
    model: str = ALIGNMENT_MODEL,
    context_screens: Optional[list[tuple[int, Image.Image]]] = None,
    platform: Optional[PlatformContext] = None,
) -> tuple[dict[str, Any], Any]:
    """
    context_screens: (page_number, image) pairs for every *other* screen in
    the same design upload, sent as low-detail thumbnails so the model can
    tell when a requirement is satisfied elsewhere in the flow instead of
    wrongly flagging it missing on this one.

    platform: the project's name and vision, so a screen from a different
    product can be recognised.
    """
    if len(approved_stories) > ALIGNMENT_MAX_STORIES_INLINE:
        raise ValueError(
            f"{len(approved_stories)} approved stories exceeds "
            f"ALIGNMENT_MAX_STORIES_INLINE={ALIGNMENT_MAX_STORIES_INLINE} — passing all of "
            "them inline in one prompt is no longer a safe default. This needs real "
            "retrieval (search.py) instead of a bigger inline dump; raising rather than "
            "guessing at a truncation."
        )

    content = [
        {
            "type": "text",
            "text": _build_prompt(approved_stories, has_context_screens=bool(context_screens), platform=platform),
        }
    ]
    if context_screens:
        for page_num, img in context_screens:
            content.append({"type": "text", "text": f"[Context — screen {page_num}]"})
            content.append(image_to_data_url(img, detail="low"))
    content.append({"type": "text", "text": "[FOCUS screen to evaluate]"})
    content.append(image_to_data_url(screen_image, detail=ALIGNMENT_IMAGE_DETAIL))

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        max_tokens=1024,
    )

    raw = response.choices[0].message.content.strip()
    data = parse_json_object(raw)
    valid_ids = {s.external_id for s in approved_stories}
    validate_alignment(data, valid_requirement_ids=valid_ids)
    _enforce_traceability(data, valid_ids)
    return data, response.usage


def _enforce_traceability(data: dict[str, Any], valid_requirement_ids: set[str]) -> None:
    """A screen tied to no approved story can't be aligned or partly aligned:
    mark it misaligned and make sure it carries a finding that says why. The
    screen is related to a story if the model listed one in
    related_requirement_ids or raised a finding against one."""
    related = {
        rid for rid in data.get("related_requirement_ids") or [] if rid in valid_requirement_ids
    } | {f["requirement_id"] for f in data["findings"] if f["requirement_id"] in valid_requirement_ids}
    data["related_requirement_ids"] = sorted(related)
    if related:
        return
    data["status"] = "misaligned"
    if not any(f["requirement_id"] is None for f in data["findings"]):
        data["findings"].append(
            {
                "requirement_id": None,
                "issue": UNTRACED_SCREEN_ISSUE,
                "recommendation": UNTRACED_SCREEN_RECOMMENDATION,
                "bounding_box": None,
            }
        )


def validate_alignment(data: dict[str, Any], valid_requirement_ids: set[str]) -> None:
    if "status" not in data or data["status"] not in ("aligned", "partial", "misaligned"):
        raise ValueError(f"Invalid or missing status: {data.get('status')!r}")
    if "findings" not in data or not isinstance(data["findings"], list):
        raise ValueError("Alignment JSON missing or invalid 'findings' array")

    for finding in data["findings"]:
        required = ("requirement_id", "issue", "recommendation")
        if not isinstance(finding, dict) or any(k not in finding for k in required):
            raise ValueError(f"Malformed finding entry: {finding!r}")
        # A finding referencing an id outside the approved set is a soft model
        # slip, not a hard failure — findings are advisory (per the brief, there
        # is deliberately no auto-accept path), so the caller persists it with a
        # null requirement_item_id rather than dropping the finding entirely.
        if valid_requirement_ids and finding["requirement_id"] not in valid_requirement_ids:
            continue

        box = finding.get("bounding_box")
        if box is not None:
            box_keys = ("top", "left", "bottom", "right")
            if not isinstance(box, dict) or any(k not in box for k in box_keys):
                raise ValueError(f"Malformed bounding_box on finding {finding['requirement_id']!r}: {box!r}")
            try:
                top, left, bottom, right = (float(box[k]) for k in box_keys)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Non-numeric bounding_box on finding {finding['requirement_id']!r}: {box!r}"
                ) from None
            if not all(0 <= v <= 100 for v in (top, left, bottom, right)):
                raise ValueError(f"bounding_box values must be 0-100: {box!r}")
            if bottom <= top or right <= left:
                raise ValueError(f"bounding_box has zero/negative area: {box!r}")
