"""
text_ingestion.py
Creates `documents` rows for text-extracted docs (requirement / change_request)
— no FAISS/tiles/vision involved. Just persists the uploaded file to disk and
records the row, so ai/text/requirements_extractor.py has something to read.
"""

import shutil
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from ai.ingest.ingest import DATA_DIR

from ..db.models import Document
from .ingestion import _next_version

UPLOADS_DIR = DATA_DIR / "uploads"


def create_text_document(
    session: Session,
    project_id: str,
    doc_type: str,
    file_path: Path,
    original_filename: str,
    checked_against_document_id: Optional[str] = None,
    type_metadata: Optional[dict[str, Any]] = None,
) -> Document:
    doc = Document(
        project_id=project_id,
        doc_type=doc_type,
        version=_next_version(session, project_id, doc_type),
        approval_status="draft",
        source_filename=original_filename,
        checked_against_document_id=checked_against_document_id,
        type_metadata=type_metadata,
    )
    session.add(doc)
    session.flush()  # assigns doc.id

    dest_dir = UPLOADS_DIR / doc_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{doc.id}{file_path.suffix.lower()}"
    shutil.copyfile(file_path, dest_path)
    doc.source_file_path = str(dest_path)

    return doc
