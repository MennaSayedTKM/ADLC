"""
describe_screen.py
Describes a screenshot of an EXISTING product screen so an "edit existing"
Figma Make prompt can anchor its changes to real elements ("the filter bar
above the table", "the primary button at top right") instead of guessing.

Distinct from transcribe.py (which pulls requirements text out of an image):
this one describes UI structure — layout regions, components, labels, states,
visual style. Same direct GPT-4o vision pattern; no FAISS/embedding pipeline.
"""

from typing import Any

from PIL import Image

from .common import image_to_data_url

SYSTEM_PROMPT = (
    "You are a senior product designer documenting a screenshot of an existing software "
    "screen so another designer can write a precise edit instruction for it.\n\n"
    "Describe, in this order and in compact plain text (no markdown fences): (1) what the "
    "screen is and its purpose in one line; (2) layout regions from top to bottom / left to "
    "right, with approximate positions; (3) every visible component by name with its exact "
    "visible label text (buttons, inputs, tabs, table columns, filters, badges); (4) visual "
    "style: dominant colors as approximate hex values, typography feel, corner radius, "
    "density; (5) any visible state (selected item, empty, error, loading).\n\n"
    "Describe only what is actually visible — never guess at text you cannot read (write "
    "[illegible]) and never invent parts of the screen that are cropped out. No commentary, "
    "no suggestions, no preamble."
)


def describe_screen(image: Image.Image, client, model: str, detail: str, max_tokens: int) -> tuple[str, Any]:
    """Returns (description, usage) — usage is the raw OpenAI response.usage, matching
    transcribe_image()'s contract so callers log an AiCall the same way."""
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this screen per your instructions."},
                    image_to_data_url(image, detail=detail),
                ],
            },
        ],
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise ValueError("Model returned an empty description for this screenshot.")
    return text, response.usage
