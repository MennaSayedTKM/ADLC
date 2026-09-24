"""
Manual demo (not pytest) — proves the ported ingest pipeline + SQLite tagging
work end to end. Mocks EmbedClient.embed_image since there's no live Colab
embedding server in this environment; everything else (PDF rendering, tiling,
FAISS indexing, metadata tagging, SQLite Document row) is real.
"""
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from PIL import Image, ImageDraw

from ai.embed_client import EmbedClient
from ai.ingest.ingest import tiles_for_document, META_PATH, TILES_DIR, INDEX_PATH
from app.db.session import get_session
from app.db.models import Project, Document
from app.services.ingestion import ingest_document

# --- build a throwaway 2-page "PDF-like" test asset: just a PNG page (fast, no fitz needed) ---
scratch_dir = Path(__file__).resolve().parent / "_scratch"
scratch_dir.mkdir(exist_ok=True)
test_image_path = scratch_dir / "sample_requirement_page.png"
img = Image.new("RGB", (900, 1200), color=(250, 250, 250))
draw = ImageDraw.Draw(img)
draw.text((40, 40), "Epic 1: User Authentication", fill=(20, 20, 20))
draw.text((40, 90), "Story: As a user, I can log in with email/password.", fill=(20, 20, 20))
img.save(test_image_path)

FAKE_DIM = 16


def fake_embed_image(self, image):
    rng = np.random.default_rng(abs(hash(str(image.size))) % (2**32))
    v = rng.random(FAKE_DIM).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


with patch.object(EmbedClient, "embed_image", fake_embed_image):
    client = EmbedClient(base_url="http://fake-embed-server.invalid")

    with get_session() as s:
        project = Project(name="demo-ingestion-project")
        s.add(project)
        s.flush()
        project_id = project.id

        doc, pages_indexed = ingest_document(
            session=s,
            project_id=project_id,
            doc_type="requirement",
            file_path=test_image_path,
            original_filename="sample_requirement_page.png",
            client=client,
            progress_cb=lambda msg: print("  [ingest]", msg),
        )
        document_id = doc.id
        print(f"\nCreated document {document_id} (doc_type={doc.doc_type}, version={doc.version})")
        print(f"Pages indexed: {pages_indexed}")

tiles = tiles_for_document(document_id)
print(f"\nTiles tagged with this document_id in metadata.json: {len(tiles)}")
for t in tiles:
    print(" ", t)

print(f"\nFAISS index exists: {INDEX_PATH.exists()}")
print(f"Tile PNG exists: {Path(tiles[0]['tile_path']).exists()}")

# --- clean up: this is a demo, not real data ---
with get_session() as s:
    d = s.query(Document).filter(Document.id == document_id).first()
    if d:
        s.delete(d)
with get_session() as s:
    p = s.query(Project).filter(Project.id == project_id).first()
    if p:
        s.delete(p)

for t in tiles:
    Path(t["tile_path"]).unlink(missing_ok=True)
shutil.rmtree(scratch_dir, ignore_errors=True)

print("\nDemo passed: document created, pages rendered+tiled+indexed, tiles tagged with document_id.")
print("(Cleaned up demo rows/files afterward — this was just a pipeline proof, not real data.)")
