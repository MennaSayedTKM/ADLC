"""
One-off manual seeding script to visually verify the bounding-box highlight
feature — creates a throwaway demo project, NOT touching any real project.
Run only while the backend server is stopped (SQLite single-writer). Prints
the project id so a matching cleanup script can remove it afterward.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw

from ai.embed_client import EmbedClient
from app.db.models import AlignmentFinding, AlignmentReport, Document, Project, RequirementItem
from app.db.session import get_session
from app.services.ingestion import ingest_document

PROJECT_NAME = "__bbox_demo_scratch__"

scratch = Path(__file__).resolve().parent / "_bbox_seed_scratch"
scratch.mkdir(exist_ok=True)
screen_path = scratch / "login_screen.png"
img = Image.new("RGB", (900, 1300), color=(250, 250, 252))
draw = ImageDraw.Draw(img)
draw.rectangle([0, 0, 900, 90], fill=(99, 102, 241))
draw.text((30, 30), "Login Screen", fill=(255, 255, 255))
draw.rectangle([120, 500, 780, 560], outline=(60, 60, 60), width=2)
draw.text((140, 520), "[ email field ]", fill=(60, 60, 60))
draw.rectangle([120, 600, 780, 660], outline=(60, 60, 60), width=2)
draw.text((140, 620), "[ password field ]", fill=(60, 60, 60))
img.save(screen_path)


def _current_index_dim(default: int = 16) -> int:
    """Match whatever dimension the real index already committed to, if any."""
    from ai.ingest.ingest import INDEX_PATH

    if not INDEX_PATH.exists():
        return default
    import faiss

    return faiss.read_index(str(INDEX_PATH)).d


_FAKE_DIM = _current_index_dim()


def fake_embed_image(self, image):
    rng = np.random.default_rng(7)
    v = rng.random(_FAKE_DIM).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


with patch.object(EmbedClient, "embed_image", fake_embed_image):
    client = EmbedClient(base_url="http://fake-embed-server.invalid")

    with get_session() as s:
        project = Project(name=PROJECT_NAME)
        s.add(project)
        s.flush()
        project_id = project.id

        req_doc = Document(
            project_id=project_id,
            doc_type="requirement",
            version=1,
            approval_status="approved",
            source_filename="requirements.pdf",
        )
        s.add(req_doc)
        s.flush()
        req_doc_id = req_doc.id

        epic = RequirementItem(document_id=req_doc_id, type="epic", external_id="E1", text="Auth")
        s.add(epic)
        s.flush()
        story = RequirementItem(
            document_id=req_doc_id,
            type="story",
            external_id="S1",
            parent_id=epic.id,
            text="As a user, I can log in with email/password.",
            acceptance_criteria=["Shows an error on wrong password"],
        )
        s.add(story)
        s.flush()

        design_doc, pages_indexed = ingest_document(
            session=s,
            project_id=project_id,
            doc_type="design",
            file_path=screen_path,
            original_filename="login_screen.png",
            client=client,
            checked_against_document_id=req_doc_id,
        )
        design_doc_id = design_doc.id

        report = AlignmentReport(
            design_document_id=design_doc_id,
            requirements_document_id=req_doc_id,
            page=1,
            status="partial",
        )
        s.add(report)
        s.flush()

        s.add(
            AlignmentFinding(
                alignment_report_id=report.id,
                requirement_item_id=story.id,
                issue="No visible error state for a failed login attempt near the password field.",
                recommendation="Add an inline red error message directly below the password field.",
                bounding_box={"top": 44, "left": 12, "bottom": 52, "right": 88},
            )
        )

print(f"Seeded scratch demo project {project_id!r}, design doc {design_doc_id!r}.")
print(f"PROJECT_ID={project_id}")
