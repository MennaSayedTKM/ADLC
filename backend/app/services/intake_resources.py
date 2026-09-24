"""
intake_resources.py
Persists and eagerly processes IntakeResource rows — the staged-resources
model a PM assembles (primary requirements doc, meeting notes, policy
references, in PDF/.docx/image form) before running the initial extraction.
See requirements_extraction.py::run_staged_extraction() for how these get
combined into one extraction call.

Text is extracted/transcribed immediately on upload, not deferred to
extraction time, so the PM can verify what the system understood from each
resource (especially an image transcription) before it ever reaches
extraction — a resource whose processing fails is still persisted, with the
failure recorded on processing_error, rather than the whole upload failing;
one bad file shouldn't block staging the rest.
"""

import shutil
from pathlib import Path
from typing import Optional

from PIL import Image
from sqlalchemy.orm import Session

from ai.ingest.ingest import DATA_DIR
from ai.text.document_text import extract_text
from ai.vision.transcribe import transcribe_image
from config import (
    GPT4O_INPUT_COST_PER_MILLION,
    GPT4O_OUTPUT_COST_PER_MILLION,
    INTAKE_IMAGE_DETAIL,
    INTAKE_IMAGE_MAX_TOKENS,
    INTAKE_IMAGE_MODEL,
)

from ..db.models import AiCall, IntakeResource

UPLOADS_DIR = DATA_DIR / "uploads" / "intake_resources"

SUFFIX_TO_FILE_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".bmp": "image",
    ".tiff": "image",
}


def _estimate_cost(usage) -> float:
    input_cost = (usage.prompt_tokens / 1_000_000) * GPT4O_INPUT_COST_PER_MILLION
    output_cost = (usage.completion_tokens / 1_000_000) * GPT4O_OUTPUT_COST_PER_MILLION
    return round(input_cost + output_cost, 6)


def create_intake_resource(
    session: Session,
    project_id: str,
    resource_kind: str,
    file_path: Path,
    original_filename: str,
    llm_client,
    notes: Optional[str] = None,
) -> IntakeResource:
    suffix = Path(original_filename).suffix.lower()
    file_type = SUFFIX_TO_FILE_TYPE.get(suffix)
    if file_type is None:
        raise ValueError(
            f"Unsupported file type: {suffix} (expected .pdf, .docx, or an image: "
            f"{', '.join(s for s, t in SUFFIX_TO_FILE_TYPE.items() if t == 'image')})"
        )

    resource = IntakeResource(
        project_id=project_id,
        resource_kind=resource_kind,
        original_filename=original_filename,
        file_path="",  # set below, once we know resource.id
        file_type=file_type,
        notes=notes,
    )
    session.add(resource)
    session.flush()  # assigns resource.id

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = UPLOADS_DIR / f"{resource.id}{suffix}"
    shutil.copyfile(file_path, dest_path)
    resource.file_path = str(dest_path)

    try:
        if file_type == "image":
            image = Image.open(dest_path).convert("RGB")
            text, usage = transcribe_image(
                image,
                llm_client,
                model=INTAKE_IMAGE_MODEL,
                detail=INTAKE_IMAGE_DETAIL,
                max_tokens=INTAKE_IMAGE_MAX_TOKENS,
            )
            resource.extracted_text = text
            session.add(
                AiCall(
                    project_id=project_id,
                    call_type="intake_transcription",
                    model=INTAKE_IMAGE_MODEL,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                    estimated_cost_usd=_estimate_cost(usage),
                )
            )
        else:
            resource.extracted_text = extract_text(dest_path)
    except Exception as e:
        # A bad resource shouldn't block staging the rest — record the
        # failure on the resource itself so the PM sees it and can remove
        # or replace the file, rather than the whole upload erroring out.
        resource.processing_error = str(e)

    session.flush()
    return resource


def list_intake_resources(session: Session, project_id: str) -> list[IntakeResource]:
    return (
        session.query(IntakeResource)
        .filter(IntakeResource.project_id == project_id)
        .order_by(IntakeResource.uploaded_at)
        .all()
    )


def delete_intake_resource(session: Session, project_id: str, resource_id: str) -> None:
    resource = (
        session.query(IntakeResource)
        .filter(IntakeResource.id == resource_id, IntakeResource.project_id == project_id)
        .first()
    )
    if resource is None:
        raise ValueError(f"Intake resource {resource_id} not found for project {project_id}")
    file_path = Path(resource.file_path)
    session.delete(resource)
    session.flush()
    file_path.unlink(missing_ok=True)
