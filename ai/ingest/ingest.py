"""
ingest.py
Render PDFs and images to tiles, embed each tile via the Colab server,
and add them to the FAISS index + metadata store.

Ported from PixelRAG's ingest.py. Pipeline logic is
unchanged (render -> tile -> embed -> FAISS); the only addition is an optional
`document_id` tag on each tile's metadata row, so tiles can be joined back to
their structured `documents` row in SQLite instead of only by `source`/`page`.
"""

import json
import os
import sys
from pathlib import Path
from typing import Callable, Generator, Optional

import faiss
import numpy as np
from PIL import Image

from ai.embed_client import EmbedClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import PDF_DPI, MAX_TILE_PX  # noqa: E402

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
# TKMIND_DATA_DIR lets the test suite point the FAISS index/tiles/metadata at
# an isolated scratch directory instead of the real app's data/. Without
# this, a test run's mocked (fake-dimension) embeddings and a developer's
# real embedding server end up fighting over the same on-disk FAISS index,
# which hard-fails on the next write from whichever side didn't create it —
# this has actually happened in both directions during development.
DATA_DIR = Path(os.environ["TKMIND_DATA_DIR"]) if "TKMIND_DATA_DIR" in os.environ else _REPO_ROOT / "data"
TILES_DIR = DATA_DIR / "tiles"
INDEX_PATH = DATA_DIR / "index.faiss"
META_PATH = DATA_DIR / "metadata.json"

TILES_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# Metadata store helpers
# ------------------------------------------------------------------

def _load_meta() -> list:
    if META_PATH.exists():
        with open(META_PATH) as f:
            return json.load(f)
    return []


def _save_meta(meta: list):
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)


def _load_index(dim: int) -> faiss.IndexFlatIP:
    if INDEX_PATH.exists():
        return faiss.read_index(str(INDEX_PATH))
    return faiss.IndexFlatIP(dim)


def _save_index(index: faiss.IndexFlatIP):
    faiss.write_index(index, str(INDEX_PATH))


# ------------------------------------------------------------------
# Image helpers
# ------------------------------------------------------------------

def _resize_if_needed(img: Image.Image) -> Image.Image:
    w, h = img.size
    if max(w, h) <= MAX_TILE_PX:
        return img
    scale = MAX_TILE_PX / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _pdf_to_images(pdf_path: Path) -> Generator[tuple, None, None]:
    """Yield (page_number, PIL.Image) for each page of a PDF."""
    try:
        import fitz
    except ImportError:
        raise ImportError("PyMuPDF is required: pip install pymupdf")

    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(PDF_DPI / 72, PDF_DPI / 72)
    for page_num in range(len(doc)):
        pix = doc[page_num].get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        yield page_num + 1, img
    doc.close()


# ------------------------------------------------------------------
# Core ingestion
# ------------------------------------------------------------------

def ingest_file(
    file_path: Path,
    client: EmbedClient,
    progress_cb: Optional[Callable[[str], None]] = None,
    document_id: Optional[str] = None,
) -> int:
    """
    Ingest a single PDF or image file — one embedding per page.

    `document_id`, when given, is stamped onto each tile's metadata row so it
    can be joined back to the structured `documents` table in SQLite.
    """
    def _log(msg: str):
        if progress_cb:
            progress_cb(msg)

    suffix = file_path.suffix.lower()
    pages: list[tuple[int, Image.Image]] = []

    _log(f"Rendering {file_path.name} at {PDF_DPI} DPI…")

    if suffix == ".pdf":
        for page_num, img in _pdf_to_images(file_path):
            pages.append((page_num, img))
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}:
        img = Image.open(file_path).convert("RGB")
        pages.append((1, img))
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    _log(f"  {len(pages)} page(s) to embed…")

    meta = _load_meta()
    dim = None
    new_vectors = []
    new_meta = []

    for page_num, img in pages:
        img = _resize_if_needed(img)
        tile_path = TILES_DIR / f"{file_path.stem}_p{page_num:04d}.png"
        img.save(tile_path, format="PNG")

        _log(f"  Embedding page {page_num}/{len(pages)}…")
        vec = client.embed_image(img)
        new_vectors.append(np.array(vec, dtype=np.float32))
        entry = {
            "source": file_path.name,
            "page": page_num,
            "tile_path": str(tile_path),
        }
        if document_id is not None:
            entry["document_id"] = document_id
        new_meta.append(entry)
        if dim is None:
            dim = len(vec)

    if not new_vectors:
        return 0

    index = _load_index(dim)
    start_id = index.ntotal
    index.add(np.stack(new_vectors))

    for i, m in enumerate(new_meta):
        m["vector_id"] = start_id + i
        meta.append(m)

    _save_index(index)
    _save_meta(meta)

    _log(f"  Indexed {len(new_vectors)} page(s) from {file_path.name}.")
    return len(new_vectors)


def clear_index():
    if INDEX_PATH.exists():
        INDEX_PATH.unlink()
    if META_PATH.exists():
        META_PATH.unlink()
    for f in TILES_DIR.glob("*.png"):
        f.unlink()


def list_indexed_files() -> list[dict]:
    meta = _load_meta()
    seen = {}
    for m in meta:
        src = m["source"]
        if src not in seen:
            seen[src] = {"source": src, "pages": 0}
        seen[src]["pages"] += 1
    return list(seen.values())


def tiles_for_document(document_id: str) -> list[dict]:
    """All tile metadata rows for a given document_id, ordered by page."""
    meta = _load_meta()
    rows = [m for m in meta if m.get("document_id") == document_id]
    rows.sort(key=lambda m: m["page"])
    return rows
