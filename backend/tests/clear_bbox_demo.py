"""Removes the __bbox_demo_scratch__ project created by seed_bbox_demo.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai.ingest.ingest import META_PATH, tiles_for_document
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

PROJECT_NAME = "__bbox_demo_scratch__"

with get_session() as s:
    project = s.query(Project).filter(Project.name == PROJECT_NAME).first()
    if project is None:
        print("Nothing to clean up.")
        raise SystemExit(0)
    project_id = project.id
    doc_rows = s.query(Document).filter(Document.project_id == project_id).all()
    refs_by_id = {d.id: {d.checked_against_document_id, d.previous_version_id} - {None} for d in doc_rows}
    remaining = set(refs_by_id)
    doc_order: list[str] = []
    while remaining:
        leaf = next(d for d in remaining if all(d not in refs_by_id[other] for other in remaining))
        doc_order.append(leaf)
        remaining.discard(leaf)

tile_paths = []
for doc_id in doc_order:
    tile_paths += [t["tile_path"] for t in tiles_for_document(doc_id)]

with get_session() as s:
    for doc_id in doc_order:
        for row in s.query(AiCall).filter(AiCall.document_id == doc_id):
            s.delete(row)

with get_session() as s:
    for doc_id in doc_order:
        report_ids = [r.id for r in s.query(AlignmentReport).filter(AlignmentReport.design_document_id == doc_id)]
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

for tp in tile_paths:
    Path(tp).unlink(missing_ok=True)

if META_PATH.exists():
    import json

    meta = json.loads(META_PATH.read_text())
    meta = [m for m in meta if m.get("document_id") not in doc_order]
    META_PATH.write_text(json.dumps(meta, indent=2))

print(f"Deleted {PROJECT_NAME!r} and its {len(doc_order)} document(s).")
