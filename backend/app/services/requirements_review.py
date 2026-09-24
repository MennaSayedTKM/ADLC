"""
requirements_review.py
Edit/approve/versioning logic for requirement documents:

- Editing an item on a draft/in_review document mutates it in place.
- Editing an item on an *approved* document forks a new version first (copies
  every requirement_item/gap forward, chained via previous_version_id) and
  applies the edit to the copy — the brief's "re-opening for edits after
  approval creates a new version rather than mutating the approved one."
- Gaps have two resolution paths: resolve_gap_as_story() converts one into a
  real story, or set_gap_status() dismisses/reopens it — nothing is ever
  inferred as resolved automatically.
"""

from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import Document, Gap, RequirementItem
from .ingestion import _next_version


def get_latest_approved_requirements(session: Session, project_id: str) -> Optional[Document]:
    """
    The design module (and change requests) can only be checked against an
    *approved* requirements version. Picks the highest-version approved one.
    """
    return (
        session.query(Document)
        .filter(
            Document.project_id == project_id,
            Document.doc_type == "requirement",
            Document.approval_status == "approved",
        )
        .order_by(Document.version.desc())
        .first()
    )


def root_document_id(session: Session, document_id: str) -> str:
    """Walk previous_version_id back to the version FAISS tiles are tagged with."""
    doc = session.query(Document).filter(Document.id == document_id).first()
    while doc is not None and doc.previous_version_id is not None:
        doc = session.query(Document).filter(Document.id == doc.previous_version_id).first()
    return doc.id if doc else document_id


def fork_new_version(session: Session, document: Document) -> Document:
    """Copy an approved document's items/gaps into a new draft version."""
    # "confluence" is per-version publish state (that specific page for that
    # specific approved version) — a freshly forked draft hasn't been
    # published itself, so it must not inherit its predecessor's page record
    # and look already-published. Everything else in type_metadata (e.g. a
    # CR's source_change_request_id) still carries over unchanged.
    inherited_metadata = {k: v for k, v in (document.type_metadata or {}).items() if k != "confluence"}
    new_doc = Document(
        project_id=document.project_id,
        doc_type=document.doc_type,
        version=_next_version(session, document.project_id, document.doc_type),
        approval_status="draft",
        source_filename=document.source_filename,
        source_file_path=document.source_file_path,
        checked_against_document_id=document.checked_against_document_id,
        previous_version_id=document.id,
        type_metadata=inherited_metadata or None,
    )
    session.add(new_doc)
    session.flush()

    old_items = (
        session.query(RequirementItem)
        .filter(RequirementItem.document_id == document.id)
        .order_by(RequirementItem.created_at)
        .all()
    )
    # Epics first so stories can resolve parent_id to the *new* epic rows.
    old_to_new_id: dict[str, str] = {}
    for old in [i for i in old_items if i.type == "epic"]:
        new_item = RequirementItem(
            document_id=new_doc.id,
            type=old.type,
            external_id=old.external_id,
            text=old.text,
            assumptions=old.assumptions,
            dependencies=old.dependencies,
            source_reference=old.source_reference,
            origin=old.origin,
            suggestion_status=old.suggestion_status,
        )
        session.add(new_item)
        session.flush()
        old_to_new_id[old.id] = new_item.id

    for old in [i for i in old_items if i.type != "epic"]:
        new_item = RequirementItem(
            document_id=new_doc.id,
            type=old.type,
            external_id=old.external_id,
            parent_id=old_to_new_id.get(old.parent_id) if old.parent_id else None,
            text=old.text,
            description=old.description,
            acceptance_criteria=old.acceptance_criteria,
            scenarios=old.scenarios,
            error_handling=old.error_handling,
            origin=old.origin,
            suggestion_status=old.suggestion_status,
        )
        session.add(new_item)
        session.flush()
        old_to_new_id[old.id] = new_item.id

    old_gaps = (
        session.query(Gap)
        .filter(Gap.document_id == document.id)
        .order_by(Gap.created_at)
        .all()
    )
    for old in old_gaps:
        session.add(
            Gap(
                document_id=new_doc.id,
                description=old.description,
                page=old.page,
                location=old.location,
                severity=old.severity,
                status=old.status,
                resolved_as_item_id=old_to_new_id.get(old.resolved_as_item_id)
                if old.resolved_as_item_id
                else None,
            )
        )
    # Sessions here run with autoflush=False (see app/db/session.py), so
    # without this, callers that immediately re-query Gap for this document
    # (e.g. resolve_gap_as_story matching a gap across the fork) wouldn't see
    # the rows just added above — flush makes them visible within the session.
    session.flush()

    return new_doc


def _next_external_id(session: Session, document_id: str, item_type: str) -> str:
    prefix = "E" if item_type == "epic" else "S"
    rows = (
        session.query(RequirementItem.external_id)
        .filter(RequirementItem.document_id == document_id, RequirementItem.type == item_type)
        .all()
    )
    max_num = 0
    for (ext_id,) in rows:
        suffix = ext_id[len(prefix):] if ext_id.startswith(prefix) else ""
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    return f"{prefix}{max_num + 1}"


def _add_item(
    session: Session,
    document: Document,
    item_type: str,
    text: str,
    parent_id: Optional[str] = None,
    description: Optional[str] = None,
    acceptance_criteria: Optional[list] = None,
    scenarios: Optional[list] = None,
    error_handling: Optional[list] = None,
    assumptions: Optional[list] = None,
    dependencies: Optional[list] = None,
    source_reference: Optional[str] = None,
    origin: str = "pm_manual",
) -> RequirementItem:
    if item_type not in ("epic", "story"):
        raise ValueError(f"Invalid item type: {item_type!r}")
    if item_type == "story" and not parent_id:
        raise ValueError("A story must have a parent_id (its epic)")
    if origin not in ("pm_manual", "pm_ai_assisted"):
        raise ValueError(f"Invalid origin for a hand-added item: {origin!r}")

    item = RequirementItem(
        document_id=document.id,
        type=item_type,
        external_id=_next_external_id(session, document.id, item_type),
        parent_id=parent_id if item_type == "story" else None,
        text=text,
        description=description if item_type == "story" else None,
        acceptance_criteria=acceptance_criteria if item_type == "story" else None,
        scenarios=scenarios if item_type == "story" else None,
        error_handling=error_handling if item_type == "story" else None,
        assumptions=assumptions if item_type == "epic" else None,
        dependencies=dependencies if item_type == "epic" else None,
        source_reference=source_reference if item_type == "epic" else None,
        origin=origin,
    )
    session.add(item)
    session.flush()
    return item


def edit_item(
    session: Session,
    document: Document,
    item_id: str,
    text: Optional[str] = None,
    acceptance_criteria: Optional[list] = None,
    description: Optional[str] = None,
    scenarios: Optional[list] = None,
    error_handling: Optional[list] = None,
    assumptions: Optional[list] = None,
    dependencies: Optional[list] = None,
    source_reference: Optional[str] = None,
) -> tuple[Document, RequirementItem]:
    """
    Edits requirement_items row `item_id` on `document`. If `document` is
    already approved, forks a new version first and edits the corresponding
    item there instead — returns the (possibly new) document and the edited row.
    """
    target_document = document
    if document.approval_status == "approved":
        source_item = session.query(RequirementItem).filter(RequirementItem.id == item_id).first()
        if source_item is None:
            raise ValueError(f"Item {item_id} not found")

        target_document = fork_new_version(session, document)

        # The fork just copied every item with the same external_id, so the
        # forked counterpart of `item_id` is found by matching on that instead.
        item = (
            session.query(RequirementItem)
            .filter(
                RequirementItem.document_id == target_document.id,
                RequirementItem.external_id == source_item.external_id,
            )
            .first()
        )
    else:
        item = (
            session.query(RequirementItem)
            .filter(RequirementItem.id == item_id, RequirementItem.document_id == document.id)
            .first()
        )

    if item is None:
        raise ValueError(f"Item {item_id} not found on document {target_document.id}")

    if text is not None:
        item.text = text
    if acceptance_criteria is not None:
        item.acceptance_criteria = acceptance_criteria
    if description is not None:
        item.description = description
    if scenarios is not None:
        item.scenarios = scenarios
    if error_handling is not None:
        item.error_handling = error_handling
    if assumptions is not None:
        item.assumptions = assumptions
    if dependencies is not None:
        item.dependencies = dependencies
    if source_reference is not None:
        item.source_reference = source_reference

    return target_document, item


def delete_item(session: Session, document: Document, item_id: str) -> Document:
    """
    Deletes a story, or an epic and every story under it together (cascade
    — a PM deleting an epic clearly means removing everything it contains,
    not leaving orphaned stories with a dangling parent_id behind). Same
    fork-on-approved rule as every other mutation here. If a deleted story
    is what a gap was resolved into, that gap reverts to "open" instead of
    pointing at a row that no longer exists — it isn't actually resolved
    anymore once the story it became is gone.
    """
    target_document = document
    if document.approval_status == "approved":
        source_item = session.query(RequirementItem).filter(RequirementItem.id == item_id).first()
        if source_item is None:
            raise ValueError(f"Item {item_id} not found")
        target_document = fork_new_version(session, document)
        item = (
            session.query(RequirementItem)
            .filter(
                RequirementItem.document_id == target_document.id,
                RequirementItem.external_id == source_item.external_id,
            )
            .first()
        )
    else:
        item = (
            session.query(RequirementItem)
            .filter(RequirementItem.id == item_id, RequirementItem.document_id == document.id)
            .first()
        )
    if item is None:
        raise ValueError(f"Item {item_id} not found on document {target_document.id}")

    ids_to_delete = [item.id]
    if item.type == "epic":
        ids_to_delete += [
            child.id
            for child in session.query(RequirementItem).filter(RequirementItem.parent_id == item.id).all()
        ]

    affected_gaps = (
        session.query(Gap)
        .filter(Gap.document_id == target_document.id, Gap.resolved_as_item_id.in_(ids_to_delete))
        .all()
    )
    for gap in affected_gaps:
        gap.status = "open"
        gap.resolved_as_item_id = None
    # Sessions here run with autoflush=False (see app/db/session.py) — the
    # bulk .delete() below issues its DELETE directly, bypassing the ORM's
    # pending UPDATEs, so without this flush the gap's FK still points at
    # the about-to-be-deleted row at the moment the DELETE runs and SQLite
    # rejects it (confirmed directly: FOREIGN KEY constraint failed).
    session.flush()

    session.query(RequirementItem).filter(RequirementItem.id.in_(ids_to_delete)).delete(synchronize_session=False)

    return target_document


def create_item(
    session: Session,
    document: Document,
    item_type: str,
    text: str,
    parent_id: Optional[str] = None,
    acceptance_criteria: Optional[list] = None,
    description: Optional[str] = None,
    scenarios: Optional[list] = None,
    error_handling: Optional[list] = None,
    assumptions: Optional[list] = None,
    dependencies: Optional[list] = None,
    source_reference: Optional[str] = None,
    origin: str = "pm_manual",
) -> tuple[Document, RequirementItem]:
    """
    Adds a new epic or story the PM writes by hand (origin="pm_manual") — or
    confirms after AI-assisted drafting (origin="pm_ai_assisted"; see
    ai/text/requirements_extractor.py's generate_item_draft) — for whatever
    extraction missed. Same fork-on-approved rule as edit_item: if
    `document` is already approved, the new item lands on a fresh forked
    version instead.
    """
    if item_type not in ("epic", "story"):
        raise ValueError(f"Invalid item type: {item_type!r}")
    if item_type == "story" and not parent_id:
        raise ValueError("A story must have a parent_id (its epic)")

    target_document = document
    resolved_parent_id = parent_id

    if document.approval_status == "approved":
        parent_external_id = None
        if parent_id:
            parent_row = session.query(RequirementItem).filter(RequirementItem.id == parent_id).first()
            if parent_row is None:
                raise ValueError(f"Parent item {parent_id} not found")
            parent_external_id = parent_row.external_id

        target_document = fork_new_version(session, document)

        if parent_external_id:
            new_parent = (
                session.query(RequirementItem)
                .filter(
                    RequirementItem.document_id == target_document.id,
                    RequirementItem.external_id == parent_external_id,
                )
                .first()
            )
            if new_parent is None:
                raise ValueError(f"Parent {parent_external_id} not found after forking new version")
            resolved_parent_id = new_parent.id
    elif parent_id:
        parent_row = (
            session.query(RequirementItem)
            .filter(RequirementItem.id == parent_id, RequirementItem.document_id == document.id)
            .first()
        )
        if parent_row is None:
            raise ValueError(f"Parent item {parent_id} not found on document {document.id}")

    item = _add_item(
        session,
        target_document,
        item_type,
        text,
        parent_id=resolved_parent_id,
        description=description,
        acceptance_criteria=acceptance_criteria,
        scenarios=scenarios,
        error_handling=error_handling,
        assumptions=assumptions,
        dependencies=dependencies,
        source_reference=source_reference,
        origin=origin,
    )
    return target_document, item


def _find_pending_suggestion(session: Session, document_id: str, item_id: str) -> RequirementItem:
    item = (
        session.query(RequirementItem)
        .filter(RequirementItem.id == item_id, RequirementItem.document_id == document_id)
        .first()
    )
    if item is None:
        raise ValueError(f"Item {item_id} not found on document {document_id}")
    if item.origin != "ai_suggestion" or item.suggestion_status != "pending":
        raise ValueError(
            f"Item {item_id} is not a pending suggestion "
            f"(origin={item.origin!r}, suggestion_status={item.suggestion_status!r})"
        )
    return item


def accept_suggestion(session: Session, document: Document, item_id: str) -> tuple[Document, RequirementItem]:
    """
    Promotes a pending ai_suggestion story into the real epic/story tree —
    it was already generated with full structure (see
    ai/text/requirements_extractor.generate_suggestions), so accepting is
    just flipping its status, not a second generation step. If the
    suggestion's own epic was itself a newly-proposed one (also pending),
    accepting the only suggestion under it surfaces that epic too — a
    suggestion can't sit in the real tree with a parent epic that's still
    hidden.
    """
    target_document = document
    if document.approval_status == "approved":
        source_item = _find_pending_suggestion(session, document.id, item_id)
        target_document = fork_new_version(session, document)
        item = (
            session.query(RequirementItem)
            .filter(
                RequirementItem.document_id == target_document.id,
                RequirementItem.external_id == source_item.external_id,
            )
            .first()
        )
        if item is None:
            raise ValueError(f"Item {item_id} not found on document {target_document.id} after forking")
    else:
        item = _find_pending_suggestion(session, document.id, item_id)

    item.suggestion_status = "accepted"

    if item.parent_id:
        parent = session.query(RequirementItem).filter(RequirementItem.id == item.parent_id).first()
        if parent is not None and parent.origin == "ai_suggestion" and parent.suggestion_status == "pending":
            parent.suggestion_status = "accepted"

    return target_document, item


def dismiss_suggestion(session: Session, document: Document, item_id: str) -> tuple[Document, RequirementItem]:
    """
    The other resolution path for a pending suggestion — kept (not
    deleted) with suggestion_status="dismissed", same as a dismissed gap,
    so it's filtered out of every view but the action is still on record.
    If this was the only pending/accepted story left under a
    newly-proposed (also pending) epic, that epic is dismissed too — an
    epic that only existed to hold this one suggestion has nothing left to
    justify staying pending.
    """
    target_document = document
    if document.approval_status == "approved":
        source_item = _find_pending_suggestion(session, document.id, item_id)
        target_document = fork_new_version(session, document)
        item = (
            session.query(RequirementItem)
            .filter(
                RequirementItem.document_id == target_document.id,
                RequirementItem.external_id == source_item.external_id,
            )
            .first()
        )
        if item is None:
            raise ValueError(f"Item {item_id} not found on document {target_document.id} after forking")
    else:
        item = _find_pending_suggestion(session, document.id, item_id)

    item.suggestion_status = "dismissed"

    if item.parent_id:
        parent = session.query(RequirementItem).filter(RequirementItem.id == item.parent_id).first()
        if parent is not None and parent.origin == "ai_suggestion" and parent.suggestion_status == "pending":
            siblings_remaining = (
                session.query(RequirementItem)
                .filter(
                    RequirementItem.parent_id == parent.id,
                    RequirementItem.id != item.id,
                    RequirementItem.suggestion_status.in_(("pending", "accepted")),
                )
                .count()
            )
            if siblings_remaining == 0:
                parent.suggestion_status = "dismissed"

    return target_document, item


def resolve_gap_as_story(
    session: Session,
    document: Document,
    gap_id: str,
    parent_id: str,
    text: Optional[str] = None,
    description: Optional[str] = None,
    acceptance_criteria: Optional[list] = None,
    scenarios: Optional[list] = None,
    error_handling: Optional[list] = None,
    origin: str = "pm_manual",
) -> tuple[Document, RequirementItem, Gap]:
    """
    Converts an open gap into a real story under `parent_id` (an epic on the
    same document) — the other resolution path is a plain dismiss via
    set_gap_status(). Same fork-on-approved rule as edit_item/create_item,
    but handled as a single fork here (not two) so the new story and the
    gap's resolved state land on the same forked document.

    Plain manual resolution (origin="pm_manual", the default) leaves
    scenarios/error_handling unset — same bare-title behavior as always,
    for a PM who wants to write the story by hand. The AI-assisted path
    (origin="pm_ai_assisted") goes through
    ai/text/requirements_extractor.generate_item_draft(kind="story",
    subject=<the gap's own description>) first — same generate-then-
    preview-then-confirm flow as the standalone "Add with AI" story
    creation, just seeded with the gap's text instead of a PM-typed
    subject — and passes the full draft's fields through here.
    """
    source_gap = session.query(Gap).filter(Gap.id == gap_id, Gap.document_id == document.id).first()
    if source_gap is None:
        raise ValueError(f"Gap {gap_id} not found on document {document.id}")
    if source_gap.status != "open":
        raise ValueError(f"Gap {gap_id} is not open (status={source_gap.status!r})")

    target_document = document
    resolved_parent_id = parent_id
    target_gap = source_gap

    if document.approval_status == "approved":
        parent_row = session.query(RequirementItem).filter(RequirementItem.id == parent_id).first()
        if parent_row is None:
            raise ValueError(f"Parent item {parent_id} not found")
        parent_external_id = parent_row.external_id

        old_gaps = (
            session.query(Gap)
            .filter(Gap.document_id == document.id)
            .order_by(Gap.created_at)
            .all()
        )
        source_gap_index = old_gaps.index(source_gap)

        target_document = fork_new_version(session, document)

        new_parent = (
            session.query(RequirementItem)
            .filter(
                RequirementItem.document_id == target_document.id,
                RequirementItem.external_id == parent_external_id,
            )
            .first()
        )
        if new_parent is None:
            raise ValueError(f"Parent {parent_external_id} not found after forking new version")
        resolved_parent_id = new_parent.id

        new_gaps = (
            session.query(Gap)
            .filter(Gap.document_id == target_document.id)
            .order_by(Gap.created_at)
            .all()
        )
        target_gap = new_gaps[source_gap_index]
    else:
        parent_row = (
            session.query(RequirementItem)
            .filter(RequirementItem.id == parent_id, RequirementItem.document_id == document.id)
            .first()
        )
        if parent_row is None:
            raise ValueError(f"Parent item {parent_id} not found on document {document.id}")

    new_item = _add_item(
        session,
        target_document,
        item_type="story",
        text=text or source_gap.description,
        parent_id=resolved_parent_id,
        description=description,
        acceptance_criteria=acceptance_criteria,
        scenarios=scenarios,
        error_handling=error_handling,
        origin=origin,
    )

    target_gap.status = "resolved"
    target_gap.resolved_as_item_id = new_item.id

    return target_document, new_item, target_gap


def set_gap_status(session: Session, document_id: str, gap_id: str, status: str) -> Gap:
    """
    The "ignore" resolution path (or reopening a dismissed gap). Resolving a
    gap by turning it into a story goes through resolve_gap_as_story()
    instead — 'resolved' isn't settable directly here, so a gap's resolved
    state always carries a resolved_as_item_id.
    """
    if status not in ("dismissed", "open"):
        raise ValueError(
            f"Invalid gap status: {status!r} — use POST .../gaps/{{gap_id}}/resolve-as-story "
            "to resolve a gap, or 'dismissed'/'open' here to ignore/reopen it"
        )
    gap = (
        session.query(Gap)
        .filter(Gap.id == gap_id, Gap.document_id == document_id)
        .first()
    )
    if gap is None:
        raise ValueError(f"Gap {gap_id} not found on document {document_id}")
    gap.status = status
    return gap


def approve_document(session: Session, document: Document) -> Document:
    if document.approval_status == "approved":
        raise ValueError("Document is already approved")
    document.approval_status = "approved"
    return document
