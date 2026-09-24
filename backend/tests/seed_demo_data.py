"""
One-off manual seeding script for a live browser demo — inserts a document +
epics/stories/gaps shaped exactly like what GPT-4o extraction would produce
(same schema, same ingestion tagging), without spending real API calls.
Not a pytest test; run directly and only while the backend server is stopped
(SQLite single-writer).
"""
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw

from ai.embed_client import EmbedClient
from app.db.models import AiCall, Gap, Project, RequirementItem
from app.db.session import get_session
from app.services.ingestion import ingest_document

PROJECT_NAME = "Acme Client Portal"

scratch = Path(__file__).resolve().parent / "_seed_scratch"
scratch.mkdir(exist_ok=True)
page_path = scratch / "acme_requirements.png"
img = Image.new("RGB", (900, 1200), color=(255, 255, 255))
ImageDraw.Draw(img).text((40, 40), "Acme Client Portal — Requirements v1", fill=(20, 20, 20))
img.save(page_path)


def fake_embed_image(self, image):
    rng = np.random.default_rng(42)
    v = rng.random(16).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


with patch.object(EmbedClient, "embed_image", fake_embed_image):
    client = EmbedClient(base_url="http://fake-embed-server.invalid")

    with get_session() as s:
        project = s.query(Project).filter(Project.name == PROJECT_NAME).first()
        if project is None:
            project = Project(name=PROJECT_NAME)
            s.add(project)
            s.flush()
        project_id = project.id

        doc, pages_indexed = ingest_document(
            session=s,
            project_id=project_id,
            doc_type="requirement",
            file_path=page_path,
            original_filename="acme_requirements.pdf",
            client=client,
        )
        document_id = doc.id

        epics_data = [
            ("E1", "User Authentication"),
            ("E2", "Client Dashboard"),
        ]
        epic_ids = {}
        for ext_id, title in epics_data:
            row = RequirementItem(document_id=document_id, type="epic", external_id=ext_id, text=title)
            s.add(row)
            s.flush()
            epic_ids[ext_id] = row.id

        stories_data = [
            ("S1", "E1", "As a user, I can log in with my email and password.",
             ["Shows an error on wrong password", "Redirects to dashboard on success"]),
            ("S2", "E1", "As a user, I can reset my password via email if I forget it.",
             ["Reset link expires after 1 hour"]),
            ("S3", "E2", "As a client, I can see a summary of my open projects on the dashboard.",
             ["Shows project name, status, and last updated date"]),
            ("S4", "E2", "As a client, I can filter the dashboard by project status.",
             []),
        ]
        for ext_id, epic_ext, text, ac in stories_data:
            s.add(
                RequirementItem(
                    document_id=document_id,
                    type="story",
                    external_id=ext_id,
                    parent_id=epic_ids[epic_ext],
                    text=text,
                    acceptance_criteria=ac,
                )
            )

        gaps_data = [
            ("No mention of session timeout duration for logged-in users.", 1, "medium"),
            ("Dashboard filter behavior when zero projects match isn't specified.", 3, "low"),
            ("No password complexity requirements stated anywhere in the document.", 1, "high"),
        ]
        for description, page, severity in gaps_data:
            s.add(Gap(document_id=document_id, description=description, page=page, severity=severity))

        s.add(
            AiCall(
                document_id=document_id,
                call_type="extraction",
                model="gpt-4o",
                input_tokens=3200,
                output_tokens=480,
                estimated_cost_usd=0.0128,
            )
        )

print(f"Seeded project {project_id!r}, document {document_id!r} ({pages_indexed} page indexed).")
print("Restart the backend server now — this script must not run while it's up (SQLite single-writer).")
