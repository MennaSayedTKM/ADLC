"""
One-off cleanup: removes the "Acme Client Portal" demo project (created by
seed_demo_data.py / seed_design_demo.py for browser demos) and wipes the
FAISS index/metadata/tiles those demo scripts populated with fake
16-dimensional vectors. Run only while the backend server is stopped
(SQLite single-writer).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai.ingest.ingest import clear_index
from app.db.models import (
    AiCall,
    AlignmentFinding,
    AlignmentReport,
    Document,
    Gap,
    Project,
    RequirementItem,
)
from app.db.session import get_session

PROJECT_NAME = "Acme Client Portal"

with get_session() as s:
    project = s.query(Project).filter(Project.name == PROJECT_NAME).first()
    if project is None:
        print(f"No {PROJECT_NAME!r} project found — nothing to clean up.")
        raise SystemExit(0)
    project_id = project.id
    doc_rows = s.query(Document).filter(Document.project_id == project_id).all()
    refs_by_id = {d.id: {d.checked_against_document_id, d.previous_version_id} - {None} for d in doc_rows}

    # Topological order: repeatedly pop a doc that no other *remaining* doc
    # points to (via checked_against_document_id/previous_version_id), so
    # every doc is deleted before whatever it references.
    remaining = set(refs_by_id)
    doc_order: list[str] = []
    while remaining:
        leaf = next(d for d in remaining if all(d not in refs_by_id[other] for other in remaining))
        doc_order.append(leaf)
        remaining.discard(leaf)

print(f"Found project {PROJECT_NAME!r} ({project_id}) with {len(doc_order)} document(s).")

with get_session() as s:
    for doc_id in doc_order:
        for row in s.query(AiCall).filter(AiCall.document_id == doc_id):
            s.delete(row)

with get_session() as s:
    for doc_id in doc_order:
        report_ids = [
            r.id for r in s.query(AlignmentReport).filter(AlignmentReport.design_document_id == doc_id)
        ]
        if report_ids:
            for row in s.query(AlignmentFinding).filter(AlignmentFinding.alignment_report_id.in_(report_ids)):
                s.delete(row)

with get_session() as s:
    for doc_id in doc_order:
        for row in s.query(AlignmentReport).filter(AlignmentReport.design_document_id == doc_id):
            s.delete(row)
        for row in s.query(Gap).filter(Gap.document_id == doc_id):
            s.delete(row)

with get_session() as s:
    for doc_id in doc_order:
        for row in s.query(RequirementItem).filter(
            RequirementItem.document_id == doc_id, RequirementItem.parent_id.isnot(None)
        ):
            s.delete(row)

with get_session() as s:
    for doc_id in doc_order:
        for row in s.query(RequirementItem).filter(RequirementItem.document_id == doc_id):
            s.delete(row)

for doc_id in doc_order:
    with get_session() as s:
        d = s.query(Document).filter(Document.id == doc_id).first()
        if d:
            s.delete(d)

with get_session() as s:
    p = s.query(Project).filter(Project.id == project_id).first()
    if p:
        s.delete(p)

print("Deleted demo project and all its documents/items/gaps/reports/findings/ai_calls.")

clear_index()
print("Cleared FAISS index, metadata.json, and tile PNGs (were 16-dim demo vectors only).")
print("Safe to restart the backend server now.")
