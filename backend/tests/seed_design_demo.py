"""
One-off manual seeding script for a live browser demo of the design review
page. Creates two design screens (login + dashboard) against the Acme
Client Portal project's approved requirements, with realistic alignment
findings — same shape run_alignment_check would produce, without spending
real API calls. Not a pytest test; run only while the backend server is
stopped (SQLite single-writer).
"""
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw

from ai.embed_client import EmbedClient
from app.db.models import AiCall, AlignmentFinding, AlignmentReport, Document, Project, RequirementItem
from app.db.session import get_session
from app.services.ingestion import ingest_document

PROJECT_NAME = "Acme Client Portal"

scratch = Path(__file__).resolve().parent / "_design_seed_scratch"
scratch.mkdir(exist_ok=True)

screens = [
    (1, "Login Screen", (99, 102, 241)),
    (2, "Client Dashboard", (16, 185, 129)),
]
screen_paths = []
for page_num, label, color in screens:
    img = Image.new("RGB", (900, 1400), color=(250, 250, 252))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 900, 90], fill=color)
    draw.text((30, 30), label, fill=(255, 255, 255))
    draw.text((40, 140), f"Mockup content for: {label}", fill=(40, 40, 40))
    path = scratch / f"screen_{page_num}.png"
    img.save(path)
    screen_paths.append(path)

# A single multi-page-looking upload — ingest_file only handles one image per
# call for non-PDF files, so we ingest the first as the "document" and add
# the second screen's tile/report manually to simulate a 2-page export.
primary_path = screen_paths[0]


def fake_embed_image(self, image):
    rng = np.random.default_rng(abs(hash(str(image.size))) % (2**32))
    v = rng.random(16).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


with patch.object(EmbedClient, "embed_image", fake_embed_image):
    client = EmbedClient(base_url="http://fake-embed-server.invalid")

    with get_session() as s:
        project = s.query(Project).filter(Project.name == PROJECT_NAME).first()
        if project is None:
            raise SystemExit(f"Project {PROJECT_NAME!r} not found — run seed_demo_data.py first")
        project_id = project.id

        req_doc = (
            s.query(Document)
            .filter(
                Document.project_id == project_id,
                Document.doc_type == "requirement",
                Document.approval_status == "approved",
            )
            .order_by(Document.version.desc())
            .first()
        )
        if req_doc is None:
            raise SystemExit("No approved requirements document found — approve one first")
        req_doc_id = req_doc.id

        story_by_external_id = {
            r.external_id: r.id
            for r in s.query(RequirementItem).filter(
                RequirementItem.document_id == req_doc_id, RequirementItem.type == "story"
            )
        }

        design_doc, pages_indexed = ingest_document(
            session=s,
            project_id=project_id,
            doc_type="design",
            file_path=primary_path,
            original_filename="acme_screens.pdf",
            client=client,
            checked_against_document_id=req_doc_id,
        )
        design_doc_id = design_doc.id

    # Manually tag the second screen's tile into metadata.json (simulating a
    # second page of the same export) since ingest_file only handles single
    # images per call for non-PDF files.
    import json

    from ai.ingest.ingest import META_PATH, TILES_DIR, INDEX_PATH
    import faiss

    second_tile_path = TILES_DIR / f"screen_2_p0002_{design_doc_id[:8]}.png"
    Image.open(screen_paths[1]).save(second_tile_path)

    meta = json.loads(META_PATH.read_text())
    index = faiss.read_index(str(INDEX_PATH))
    vec = np.array(fake_embed_image(None, Image.open(second_tile_path)), dtype=np.float32).reshape(1, -1)
    start_id = index.ntotal
    index.add(vec)
    meta.append(
        {
            "source": "acme_screens.pdf",
            "page": 2,
            "tile_path": str(second_tile_path),
            "document_id": design_doc_id,
            "vector_id": start_id,
        }
    )
    META_PATH.write_text(json.dumps(meta, indent=2))
    faiss.write_index(index, str(INDEX_PATH))

    with get_session() as s:
        report1 = AlignmentReport(
            design_document_id=design_doc_id,
            requirements_document_id=req_doc_id,
            page=1,
            status="partial",
        )
        s.add(report1)
        s.flush()
        s.add(
            AlignmentFinding(
                alignment_report_id=report1.id,
                requirement_item_id=story_by_external_id.get("S1"),
                issue="No inline error message shown for a failed login attempt.",
                recommendation="Add a red error banner below the password field when login fails.",
            )
        )

        report2 = AlignmentReport(
            design_document_id=design_doc_id,
            requirements_document_id=req_doc_id,
            page=2,
            status="aligned",
        )
        s.add(report2)

        s.add(
            AiCall(
                document_id=design_doc_id,
                call_type="alignment",
                model="gpt-4o",
                input_tokens=2100,
                output_tokens=320,
                estimated_cost_usd=0.00845,
            )
        )

print(f"Seeded design document {design_doc_id!r} with 2 screens against requirements v{req_doc.version}.")
print("Restart the backend server now.")
