from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel

# The nCubex Change Request template's own "Request Type" field — see the
# "TKMind Assessment" section of that template. Kept here as the single
# source of truth so the router's Form(...) parameter and any future
# frontend-facing schema both validate against the exact same set.
CrRequestType = Literal[
    "New Feature",
    "Enhancement",
    "Configuration",
    "Report",
    "Integration",
    "Business Support",
]


class AcceptanceCriterionIO(BaseModel):
    text: str
    out_of_scope: bool = False


class ScenarioIO(BaseModel):
    title: str
    given: str
    when: str
    then: str
    source_reference: Optional[str] = None


class ErrorHandlingIO(BaseModel):
    condition: str
    message: str


class GapOut(BaseModel):
    id: str
    description: str
    page: Optional[int] = None
    location: Optional[str] = None
    severity: str
    status: str
    resolved_as_item_id: Optional[str] = None

    model_config = {"from_attributes": True}


class RequirementItemOut(BaseModel):
    id: str
    type: str
    external_id: str
    parent_id: Optional[str] = None
    text: str
    description: Optional[str] = None
    scenarios: Optional[list[ScenarioIO]] = None
    acceptance_criteria: Optional[list[AcceptanceCriterionIO]] = None
    error_handling: Optional[list[ErrorHandlingIO]] = None
    assumptions: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None
    source_reference: Optional[str] = None
    origin: str = "extracted"
    suggestion_status: Optional[str] = None

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    project_id: str
    doc_type: str
    version: int
    approval_status: str
    source_filename: str
    previous_version_id: Optional[str] = None
    checked_against_document_id: Optional[str] = None
    type_metadata: Optional[dict[str, Any]] = None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class KeyFindingOut(BaseModel):
    # category is one of "Source material" | "Stories" | "Advisory content" —
    # which review agent raised it, so the PM can trace a finding back to
    # what it's about (see services/requirements_evaluation.py's
    # _CATEGORY_* constants).
    category: str
    text: str


class EvaluationReportOut(BaseModel):
    id: str
    document_id: str
    input_quality_score: int
    output_quality_score: int
    input_summary: str
    output_summary: str
    key_findings: list[KeyFindingOut]
    recommendations: list[str]
    signals: dict[str, int]
    weak_story_ids: list[str]
    # The three review agents' own raw scores, shown per-category in the UI
    # alongside the blended input/output headline scores above.
    source_material_score: int
    stories_score: int
    advisory_content_score: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RequirementsDetail(BaseModel):
    document: DocumentOut
    epics: list[RequirementItemOut]
    stories: list[RequirementItemOut]
    gaps: list[GapOut]
    unresolved_gap_count: int
    # Pending ai_suggestion items only (epic or story) — the PM hasn't
    # accepted or dismissed these yet, so they're kept out of epics/stories
    # above until they are. See routers/requirements.py's _detail_for.
    suggestions: list[RequirementItemOut] = []
    # None until the PM runs an on-demand evaluation (see
    # services/requirements_evaluation.py) — never computed automatically.
    evaluation: Optional[EvaluationReportOut] = None


class ItemUpdate(BaseModel):
    text: Optional[str] = None
    description: Optional[str] = None
    scenarios: Optional[list[ScenarioIO]] = None
    acceptance_criteria: Optional[list[AcceptanceCriterionIO]] = None
    error_handling: Optional[list[ErrorHandlingIO]] = None
    assumptions: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None
    source_reference: Optional[str] = None  # epics only


class ItemCreate(BaseModel):
    type: str  # "epic" | "story"
    text: str
    parent_id: Optional[str] = None  # required for stories, ignored for epics
    description: Optional[str] = None
    scenarios: Optional[list[ScenarioIO]] = None
    acceptance_criteria: Optional[list[AcceptanceCriterionIO]] = None
    error_handling: Optional[list[ErrorHandlingIO]] = None
    assumptions: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None
    source_reference: Optional[str] = None  # epics only
    # "pm_manual" (default) for a hand-typed item, "pm_ai_assisted" when the
    # PM is confirming a draft from POST .../items/generate-draft.
    origin: Optional[str] = None


class ItemDraftRequest(BaseModel):
    kind: str  # "epic" | "story" | "acceptance_criterion" | "scenario" | "error_handling"
    subject: str
    parent_id: Optional[str] = None  # the epic (for a story) or the story (for the rest)
    # This call's own prior response, when the PM clicked Regenerate rather
    # than confirming — see generate_item_draft()'s docstring for why.
    previous_draft: Optional[dict[str, Any]] = None


class EpicDraftOut(BaseModel):
    title: str
    assumptions: list[str]
    dependencies: list[str]


class StoryDraftOut(BaseModel):
    title: str
    description: str
    scenarios: list[ScenarioIO]
    acceptance_criteria: list[AcceptanceCriterionIO]
    error_handling: list[ErrorHandlingIO]


class AcDraftOut(BaseModel):
    text: str
    out_of_scope: bool = False


class GapStatusUpdate(BaseModel):
    status: str  # "dismissed" | "open" — resolve via POST .../gaps/{gap_id}/resolve-as-story instead


class GapResolveAsStory(BaseModel):
    parent_id: str  # epic to attach the new story under
    text: Optional[str] = None  # defaults to the gap's own description
    description: Optional[str] = None
    scenarios: Optional[list[ScenarioIO]] = None
    acceptance_criteria: Optional[list[AcceptanceCriterionIO]] = None
    error_handling: Optional[list[ErrorHandlingIO]] = None
    # "pm_manual" (default) for a hand-written resolution, "pm_ai_assisted"
    # when confirming a draft from POST .../items/generate-draft seeded
    # with this gap's own description.
    origin: Optional[str] = None


class TextIngestResponse(BaseModel):
    document: DocumentOut
    epics_extracted: int
    stories_extracted: int
    gaps_found: int


class ConfluencePublishResponse(BaseModel):
    document: DocumentOut
    page_id: str
    page_url: str


class ChangeRequestIngestResponse(BaseModel):
    change_request_document: DocumentOut
    requirements_document: DocumentOut
    epics_extracted: int
    stories_extracted: int
    gaps_found: int
