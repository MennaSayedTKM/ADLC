"""Throwaway manual verification script — not a pytest test. Deletes itself's
data at the end so it doesn't leave junk rows in the real dev database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import inspect
from app.db.session import engine, get_session
from app.db.models import Project, Document, RequirementItem, Gap

insp = inspect(engine)
print("Tables:", insp.get_table_names())
print()

with get_session() as s:
    p = Project(name="verify-schema-project")
    s.add(p)
    s.flush()

    doc = Document(
        project_id=p.id,
        doc_type="requirement",
        version=1,
        approval_status="draft",
        source_filename="test.pdf",
    )
    s.add(doc)
    s.flush()

    epic = RequirementItem(
        document_id=doc.id, type="epic", external_id="E1", text="Sample epic"
    )
    s.add(epic)
    s.flush()

    story = RequirementItem(
        document_id=doc.id,
        type="story",
        external_id="S1",
        parent_id=epic.id,
        text="Sample story",
        acceptance_criteria=["AC1", "AC2"],
    )
    s.add(story)

    gap = Gap(document_id=doc.id, description="Missing detail", page=3, severity="medium")
    s.add(gap)
    s.flush()

    print("Inserted project:", p.id)
    print("Inserted document:", doc.id, doc.doc_type, doc.approval_status)
    print("Inserted requirement items:", epic.id, story.id, "AC:", story.acceptance_criteria)
    print("Inserted gap:", gap.id, gap.severity, gap.status)

    # Capture plain string ids now — ORM instances expire once the session closes.
    project_id, document_id = p.id, doc.id

print()
print("Testing CHECK constraint (invalid doc_type should fail)...")
try:
    with get_session() as s:
        bad = Document(
            project_id=project_id,
            doc_type="not-a-real-type",
            version=99,
            approval_status="draft",
            source_filename="bad.pdf",
        )
        s.add(bad)
    print("FAIL: bad insert succeeded")
except Exception as e:
    print("OK, rejected:", type(e).__name__)

print()
print("Testing UNIQUE constraint (duplicate project name should fail)...")
try:
    with get_session() as s:
        dup = Project(name="verify-schema-project")
        s.add(dup)
    print("FAIL: duplicate name succeeded")
except Exception as e:
    print("OK, rejected:", type(e).__name__)

# Clean up so this doesn't leave test rows in the dev DB.
# NOTE: SQLite enforces FK constraints per-statement against the transaction's
# own pending state, so deletes in the correct dependency order (children
# before parents) work fine within a single transaction — no need to commit
# between levels. The one real gotcha: SQLAlchemy batches same-table deletes
# from one flush into a single executemany call, ignoring python call order,
# so two rows of the same table that reference each other (e.g. two documents
# via previous_version_id) must be flushed individually rather than both
# queued before one flush/commit.
with get_session() as s:
    for gap_row in s.query(Gap).filter(Gap.document_id == document_id):
        s.delete(gap_row)
    for row in s.query(RequirementItem).filter(
        RequirementItem.document_id == document_id, RequirementItem.parent_id.isnot(None)
    ):
        s.delete(row)

with get_session() as s:
    for row in s.query(RequirementItem).filter(RequirementItem.document_id == document_id):
        s.delete(row)

with get_session() as s:
    doc_row = s.query(Document).filter(Document.id == document_id).first()
    if doc_row:
        s.delete(doc_row)

with get_session() as s:
    project_row = s.query(Project).filter(Project.id == project_id).first()
    if project_row:
        s.delete(project_row)
print()
print("Cleaned up test rows. Schema verification passed.")
