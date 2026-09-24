"""
transcribe.py
Transcribes a single image (a whiteboard photo, a screenshot, a diagram) into
plain text relevant to requirements gathering — the vision-side counterpart
to ai/text/document_text.py's PDF/.docx text extraction, so an image-based
intake resource merges into the exact same downstream extraction pipeline as
every other resource.

Deliberately does NOT go through ai/ingest/ingest.py's render->tile->embed->
FAISS pipeline: that machinery exists for retrieval (design-screen search),
which a one-off transcription doesn't need, and it requires EmbedClient/
EMBED_API_URL (an external Colab/ngrok dependency) this feature has no
reason to depend on. Calls GPT-4o vision directly, the same pattern
ai/vision/alignment_checker.py::check_alignment already established.
"""

from typing import Any

from PIL import Image

from .common import image_to_data_url

SYSTEM_PROMPT = (
    "You are transcribing an image supplied as one input resource for a software "
    "requirements-gathering process. The image might be a photo of a whiteboard from "
    "a workshop, a screenshot of an existing system or tool, a diagram, or a page of "
    "handwritten notes.\n\n"
    "Transcribe everything in the image that could plausibly matter to requirements: "
    "all text (typed or handwritten), labels on diagram boxes/arrows and what they "
    "connect, table contents, and a plain description of any flow or structure the "
    "image conveys that isn't literal text (e.g. \"a flowchart showing Order -> "
    "Payment -> Fulfillment, with a dashed line back from Payment to Order labeled "
    "'declined'\"). Preserve structure where it's meaningful (keep a list a list, "
    "keep a table a table) using plain text formatting — no markdown code fences.\n\n"
    "Transcribe only what's actually visible — never guess at illegible handwriting or "
    "infer content that isn't there; write [illegible] for text you genuinely cannot "
    "read rather than a plausible-looking guess. If the image has nothing relevant to "
    "requirements at all, say so in one line rather than describing it at length.\n\n"
    "Return plain transcribed text only — no commentary about the task, no preamble."
)


def transcribe_image(image: Image.Image, client, model: str, detail: str, max_tokens: int) -> tuple[str, Any]:
    """Returns (transcribed_text, usage) — usage is the raw OpenAI response.usage
    object, matching check_alignment()'s (data, response.usage) contract so callers
    can log an AiCall the same way."""
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this image per your instructions."},
                    image_to_data_url(image, detail=detail),
                ],
            },
        ],
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise ValueError("Model returned an empty transcription for this image.")
    return text, response.usage
