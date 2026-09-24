"""
ingestion.py
Bridges the ported PixelRAG ingest pipeline (ai/ingest/ingest.py) to the
SQLite `documents` table: creates a Document row first (so ingest_file can
tag every tile with its document_id), then runs the render -> tile -> embed
-> FAISS pipeline unchanged.
"""

from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ai.embed_client import EmbedClient
from ai.ingest.ingest import ingest_file

from ..db.models import Document


def _next_version(session: Session, project_id: str, doc_type: str) -> int:
    current_max = (
        session.query(func.max(Document.version))
        .filter(Document.project_id == project_id, Document.doc_type == doc_type)
        .scalar()
    )
    return (current_max or 0) + 1


def ingest_document(
    session: Session,
    project_id: str,
    doc_type: str,
    file_path: Path,
    original_filename: str,
    client: EmbedClient,
    checked_against_document_id: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[Document, int]:
    """
    Create a `documents` row and ingest `file_path`'s pages into FAISS/tiles,
    tagged with the new row's id. Returns (document, pages_indexed).
    """
    doc = Document(
        project_id=project_id,
        doc_type=doc_type,
        version=_next_version(session, project_id, doc_type),
        approval_status="draft",
        source_filename=original_filename,
        checked_against_document_id=checked_against_document_id,
    )
    session.add(doc)
    session.flush()  # assigns doc.id without committing yet

    pages_indexed = ingest_file(
        file_path, client, progress_cb=progress_cb, document_id=doc.id
    )
    return doc, pages_indexed
