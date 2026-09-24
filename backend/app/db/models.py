"""
models.py
SQLAlchemy models for the TKMiND structured data store (SQLite).

Everything here is workflow/structure metadata — the FAISS index and tile PNGs
stay exactly as they were in PixelRAG, referenced from `documents.id` instead of
only `source`/`page` (see ai/ingest/ingest.py).
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import JSON

from .base import Base, new_uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    # {"index_page_id": "...", "index_page_url": "..."} — the Confluence
    # page every published requirements version for this project links
    # under, created once on first publish and reused after. Named
    # "confluence_metadata" rather than "metadata" — the latter collides
    # with SQLAlchemy's own reserved Base.metadata attribute.
    confluence_metadata = Column(JSON, nullable=True)


class Document(Base):
    """
    The generalizable table future modules (dev/QA/PM-delivery) will also use.
    doc_type distinguishes requirement docs from design docs; both are ingested
    through the same ingest_file() -> FAISS/tile pipeline.
    """

    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=new_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    doc_type = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    approval_status = Column(String, nullable=False, default="draft")
    source_filename = Column(String, nullable=False)

    # Design docs only: which approved requirements version this was checked against.
    checked_against_document_id = Column(String, ForeignKey("documents.id"), nullable=True)

    # Requirement docs only: re-opening an approved version creates a new row
    # here rather than mutating the approved one; this chains back to the prior version.
    previous_version_id = Column(String, ForeignKey("documents.id"), nullable=True)

    uploaded_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    # Where the original uploaded file (PDF/.docx) lives on disk — kept for
    # reference even though requirement/change_request docs no longer go
    # through the FAISS/tile pipeline (text extraction only, not vision).
    source_file_path = Column(String, nullable=True)

    # doc_type-specific metadata that doesn't belong on every document (e.g.
    # a change_request's Request Type/Classification/Estimated Effort/Cost).
    # Generic JSON bucket rather than bolting on CR-only columns, matching
    # the brief's own "generic documents table" intent.
    type_metadata = Column(JSON, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "doc_type in ('requirement','design','change_request')", name="ck_documents_doc_type"
        ),
        CheckConstraint(
            "approval_status in ('draft','in_review','approved')",
            name="ck_documents_approval_status",
        ),
        UniqueConstraint("project_id", "doc_type", "version", name="uq_documents_project_type_version"),
    )


class RequirementItem(Base):
    __tablename__ = "requirement_items"

    id = Column(String, primary_key=True, default=new_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    type = Column(String, nullable=False)
    external_id = Column(String, nullable=False)  # "E1"/"S1" from the extraction JSON
    parent_id = Column(String, ForeignKey("requirement_items.id"), nullable=True)
    text = Column(Text, nullable=False)  # title/summary for both epics and stories
    acceptance_criteria = Column(JSON, nullable=True)  # list[{"text": str, "out_of_scope": bool}]

    # Stories only, from here down — populated when the source document
    # supports this level of detail (see ai/text/requirements_extractor.py's
    # "infer, don't fabricate" discipline); null/empty otherwise, not guessed.
    description = Column(Text, nullable=True)  # the As-a/I-want/so-that narrative
    scenarios = Column(JSON, nullable=True)  # list[{"title","given","when","then","source_reference"}]
    error_handling = Column(JSON, nullable=True)  # list[{"condition","message"}]

    # Epics only: stated (not invented) assumptions/dependencies from the source doc.
    assumptions = Column(JSON, nullable=True)  # list[str]
    dependencies = Column(JSON, nullable=True)  # list[str]

    # Epics only: the source section/subsection this epic is grounded in (e.g.
    # "4.1.A"), for traceability — a story's own traceability lives per-scenario
    # inside the scenarios JSON above, since a story can span multiple source bullets.
    source_reference = Column(String, nullable=True)

    # Provenance — how this item came to exist, so the PM can tell extracted
    # content apart from content that was added afterward. "extracted": came
    # straight from the source document. "pm_manual": the PM typed it by
    # hand. "pm_ai_assisted": the PM gave the AI a subject and it drafted the
    # rest (still reviewed/confirmed by the PM before saving). "ai_suggestion":
    # the AI proposed it unprompted (see suggestion_status below) — never
    # grounded in the source document, so source_reference is never a real
    # citation for anything but "extracted".
    origin = Column(String, nullable=False, default="extracted", server_default="extracted")

    # ai_suggestion items only: "pending" until the PM accepts or dismisses
    # it. null for every other origin — those are already final the moment
    # they're created, there's no separate suggestion lifecycle for them.
    # Accepted/dismissed rows are never deleted, just filtered out of the
    # main epic/story views (see routers/requirements.py's _detail_for),
    # matching how a dismissed gap is kept, not deleted.
    suggestion_status = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        CheckConstraint("type in ('epic','story')", name="ck_requirement_items_type"),
        CheckConstraint(
            "origin in ('extracted','pm_manual','pm_ai_assisted','ai_suggestion')",
            name="ck_requirement_items_origin",
        ),
        CheckConstraint(
            "suggestion_status is null or suggestion_status in ('pending','accepted','dismissed')",
            name="ck_requirement_items_suggestion_status",
        ),
        UniqueConstraint("document_id", "external_id", name="uq_requirement_items_doc_external_id"),
    )


class Gap(Base):
    __tablename__ = "gaps"

    id = Column(String, primary_key=True, default=new_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    description = Column(Text, nullable=False)
    page = Column(Integer, nullable=True)  # PDFs only — .docx has no reliable page concept
    # A section heading or short quote pinpointing where in the source text
    # this gap was noticed — more actionable than a page number now that
    # there's no rendered page image to look at (text extraction, not vision).
    location = Column(Text, nullable=True)
    severity = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    # Set when a PM resolves a gap by turning it into a real story, so the
    # gap keeps a record of what it became rather than just disappearing.
    resolved_as_item_id = Column(String, ForeignKey("requirement_items.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint("severity in ('low','medium','high')", name="ck_gaps_severity"),
        CheckConstraint("status in ('open','resolved','dismissed')", name="ck_gaps_status"),
    )


class AlignmentReport(Base):
    """One row per screen (= one page of a design document)."""

    __tablename__ = "alignment_reports"

    id = Column(String, primary_key=True, default=new_uuid)
    design_document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    requirements_document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    page = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "status in ('aligned','partial','misaligned')", name="ck_alignment_reports_status"
        ),
    )


class AlignmentFinding(Base):
    __tablename__ = "alignment_findings"

    id = Column(String, primary_key=True, default=new_uuid)
    alignment_report_id = Column(String, ForeignKey("alignment_reports.id"), nullable=False)
    requirement_item_id = Column(String, ForeignKey("requirement_items.id"), nullable=True)
    issue = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=False)
    # {"top": n, "left": n, "bottom": n, "right": n} as percentages of the
    # screen image (0=top/left, 100=bottom/right) — same convention as the
    # ported answer.py's _locate_and_crop. Null when the issue isn't tied to
    # a specific visible region (e.g. something's entirely absent).
    bounding_box = Column(JSON, nullable=True)
    resolution_status = Column(String, nullable=False, default="open")
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "resolution_status in ('open','resolved','dismissed')",
            name="ck_alignment_findings_resolution_status",
        ),
    )


class AiCall(Base):
    """
    GPT-4o call log — counts/costs, not free at volume. document_id is
    nullable and project_id was added alongside it: intake-resource
    processing (see IntakeResource) happens before any Document exists yet
    (a PM stages resources, including image transcription calls, ahead of
    running extraction), so those calls log against project_id instead.
    Every pre-existing call type still always supplies document_id.
    """

    __tablename__ = "ai_calls"

    id = Column(String, primary_key=True, default=new_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=True)
    call_type = Column(String, nullable=False)
    model = Column(String, nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Numeric, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "call_type in ('extraction','alignment','rerank','crop','synthesis',"
            "'suggestions','item_draft','intake_transcription','clarifying_questions',"
            "'policy_coverage','source_material_review','output_story_review',"
            "'artifact_quality_review')",
            name="ck_ai_calls_call_type",
        ),
    )


class IntakeResource(Base):
    """
    A single resource (requirements doc, meeting notes, policy reference,
    etc.) a PM has staged for a project ahead of running the initial
    extraction — see requirements_extraction.py::run_staged_extraction().
    Several of these get combined into one extraction call; none of them
    are a Document themselves. extracted_text is populated eagerly at
    upload time (direct text extraction for PDF/DOCX, GPT-4o vision
    transcription for images) so the PM can verify it before it ever
    reaches extraction.
    """

    __tablename__ = "intake_resources"

    id = Column(String, primary_key=True, default=new_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    resource_kind = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    # Null while a resource is still processing (or if processing failed —
    # see processing_error); populated once extraction/transcription completes.
    extracted_text = Column(Text, nullable=True)
    processing_error = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "resource_kind in ('primary_requirements','meeting_notes','policy_reference','other')",
            name="ck_intake_resources_resource_kind",
        ),
        CheckConstraint(
            "file_type in ('pdf','docx','image')",
            name="ck_intake_resources_file_type",
        ),
    )


class ClarifyingQuestion(Base):
    """
    An AI-generated, plain-language question for a non-technical business
    stakeholder, produced from a project's staged IntakeResources — see
    ai/text/requirements_extractor.py::generate_clarifying_questions(). Purely
    advisory: never blocks running extraction, answering is never mandatory.
    A PM relays the question externally and records the client's answer
    here; answered questions become part of the combined extraction input.
    """

    __tablename__ = "clarifying_questions"

    id = Column(String, primary_key=True, default=new_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    topic_area = Column(String, nullable=True)
    why_it_matters = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")
    answer_text = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    answered_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status in ('pending','answered','skipped')",
            name="ck_clarifying_questions_status",
        ),
    )


class StandingPolicy(Base):
    """
    One of TKMiND's own standing default requirements — global, not
    per-project, PM-managed. Injected into every initial extraction as a
    fallback-only source: applied only where the client's own staged
    material doesn't already address the same topic (see
    run_staged_extraction() / _shared_instructions()'s TKMIND STANDARD
    POLICIES section). The client's own material always wins on conflict.
    """

    __tablename__ = "standing_policies"

    id = Column(String, primary_key=True, default=new_uuid)
    title = Column(String, nullable=False)
    policy_text = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class EvaluationReport(Base):
    """
    On-demand quality evaluation of a requirements document's CURRENT
    visible tree — one row per document_id (unique), a point-in-time
    snapshot of the current version, not a history log; re-running the
    evaluation replaces this row rather than adding a new one. See
    backend/app/services/requirements_evaluation.py::run_evaluation().
    """

    __tablename__ = "evaluation_reports"

    id = Column(String, primary_key=True, default=new_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False, unique=True)
    input_quality_score = Column(Integer, nullable=False)
    output_quality_score = Column(Integer, nullable=False)
    input_summary = Column(Text, nullable=False)
    output_summary = Column(Text, nullable=False)
    key_findings = Column(JSON, nullable=False)  # list[{"category": str, "text": str}] — the "main points"
    recommendations = Column(JSON, nullable=False)  # list[str] — deterministic, actionable
    signals = Column(JSON, nullable=False)  # deterministic counts feeding the scores, for a transparent "why"
    weak_story_ids = Column(JSON, nullable=False)  # list[str] external_ids the output agent flagged
    # The three review agents' own raw 0-100 scores, kept alongside the two
    # blended headline scores above — shown per-category in the UI (one
    # meter per Key Findings section) so the PM can see which specific
    # review is dragging a headline score down, not just the blended total.
    source_material_score = Column(Integer, nullable=False)
    stories_score = Column(Integer, nullable=False)
    advisory_content_score = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        CheckConstraint("input_quality_score between 0 and 100", name="ck_evaluation_reports_input_score"),
        CheckConstraint("output_quality_score between 0 and 100", name="ck_evaluation_reports_output_score"),
        CheckConstraint("source_material_score between 0 and 100", name="ck_evaluation_reports_source_score"),
        CheckConstraint("stories_score between 0 and 100", name="ck_evaluation_reports_stories_score"),
        CheckConstraint("advisory_content_score between 0 and 100", name="ck_evaluation_reports_advisory_score"),
    )
