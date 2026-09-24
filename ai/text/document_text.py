"""
document_text.py
Extracts real text from requirement/CR source documents — PDF (via PyMuPDF's
text layer) and Word .docx (via python-docx) — instead of rendering pages to
images. This is a text-extraction task, not a visual one; there's no vision
model or embedding step in this path.

Legacy binary .doc is not supported (needs a different toolchain entirely —
raise clearly rather than silently mis-reading it).
"""

from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx"}


def extract_text(file_path: Path) -> str:
    """
    Returns the document's text as a single string, with light structural
    markers (page breaks for PDF) preserved so the model can still cite
    "page 4" the way it could when reading rendered page images.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(file_path)
    if suffix == ".docx":
        return _extract_docx_text(file_path)
    if suffix == ".doc":
        raise ValueError(
            "Legacy .doc files aren't supported — please save/export as .docx or PDF."
        )
    raise ValueError(f"Unsupported file type for text extraction: {suffix}")


def _extract_pdf_text(file_path: Path) -> str:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(str(file_path))
    except fitz.FileDataError:
        raise ValueError(
            f"Could not open '{file_path.name}' as a PDF — it may be corrupted or incomplete "
            "(a common cause: an interrupted download or copy). Please re-export or re-download "
            "it and try again."
        )
    try:
        parts = []
        for page_num in range(len(doc)):
            text = doc[page_num].get_text().strip()
            if text:
                parts.append(f"--- Page {page_num + 1} ---\n{text}")
        return "\n\n".join(parts)
    finally:
        doc.close()


def _extract_docx_text(file_path: Path) -> str:
    """
    Walks the document body in original order (not paragraphs-then-tables
    separately) so a CR form's "Label | Value" table rows stay next to the
    prose around them, matching how the source document actually reads.
    """
    import docx
    from docx.opc.exceptions import PackageNotFoundError
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(str(file_path))
    except PackageNotFoundError:
        raise ValueError(
            f"Could not open '{file_path.name}' as a Word document — it may be corrupted, "
            "incomplete, or not actually a .docx file (a common cause: an interrupted "
            "download or copy). Please re-export or re-download it and try again."
        )
    parts = []

    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            para = Paragraph(child, document)
            if para.text.strip():
                parts.append(para.text.strip())
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            parts.append(_render_table(table))

    return "\n".join(parts)


def _render_table(table) -> str:
    rows = []
    for row in table.rows:
        cells = [c.text.strip() for c in row.cells]
        if not any(cells):
            continue
        # Two-column rows (the common CR-form pattern) read better as
        # "Label: Value" than as a pipe-joined row.
        if len(cells) == 2:
            rows.append(f"{cells[0]}: {cells[1]}")
        else:
            rows.append(" | ".join(cells))
    return "\n".join(rows)
