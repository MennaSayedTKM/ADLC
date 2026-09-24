// Mirrors backend/app/schemas/{projects,requirements}.py — keep in sync by hand
// (no shared codegen yet; this is a small enough surface that it's not worth
// the build-step complexity of introducing one).

export type ApprovalStatus = 'draft' | 'in_review' | 'approved'
export type DocType = 'requirement' | 'design' | 'change_request'
export type Severity = 'low' | 'medium' | 'high'
export type GapStatus = 'open' | 'resolved' | 'dismissed'
export type ItemType = 'epic' | 'story'
export type ItemOrigin = 'extracted' | 'pm_manual' | 'pm_ai_assisted' | 'ai_suggestion'
export type SuggestionStatus = 'pending' | 'accepted' | 'dismissed'
export type DraftKind = 'epic' | 'story' | 'acceptance_criterion' | 'scenario' | 'error_handling'
export type AlignmentStatus = 'aligned' | 'partial' | 'misaligned'
export type FindingStatus = 'open' | 'resolved' | 'dismissed'
// The nCubex Change Request template's own "Request Type" field (TKMind
// Assessment section) — kept in sync by hand with CrRequestType in
// backend/app/schemas/requirements.py.
export type CrRequestType =
  | 'New Feature'
  | 'Enhancement'
  | 'Configuration'
  | 'Report'
  | 'Integration'
  | 'Business Support'
// Mirrors IntakeResourceKind in backend/app/schemas/intake.py.
export type IntakeResourceKind = 'primary_requirements' | 'meeting_notes' | 'policy_reference' | 'other'
export type IntakeFileType = 'pdf' | 'docx' | 'image'
export type ClarifyingQuestionStatus = 'pending' | 'answered' | 'skipped'

export interface Project {
  id: string
  name: string
  created_at: string
}

export interface Document {
  id: string
  project_id: string
  doc_type: DocType
  version: number
  approval_status: ApprovalStatus
  source_filename: string
  previous_version_id: string | null
  checked_against_document_id: string | null
  type_metadata: Record<string, unknown> | null
  uploaded_at: string
}

export interface AcceptanceCriterion {
  text: string
  out_of_scope: boolean
}

export interface Scenario {
  title: string
  given: string
  when: string
  then: string
  source_reference: string | null
}

export interface ErrorHandlingEntry {
  condition: string
  message: string
}

export interface RequirementItem {
  id: string
  type: ItemType
  external_id: string
  parent_id: string | null
  text: string
  description: string | null
  scenarios: Scenario[] | null
  acceptance_criteria: AcceptanceCriterion[] | null
  error_handling: ErrorHandlingEntry[] | null
  assumptions: string[] | null
  dependencies: string[] | null
  source_reference: string | null // epics only
  origin: ItemOrigin
  suggestion_status: SuggestionStatus | null // ai_suggestion items only
}

export interface Gap {
  id: string
  description: string
  page: number | null
  location: string | null
  severity: Severity
  status: GapStatus
  resolved_as_item_id: string | null
}

export type EvaluationFindingCategory = 'Source material' | 'Stories' | 'Advisory content'

export interface EvaluationFinding {
  category: EvaluationFindingCategory
  text: string
}

export interface EvaluationReport {
  id: string
  document_id: string
  input_quality_score: number
  output_quality_score: number
  input_summary: string
  output_summary: string
  key_findings: EvaluationFinding[]
  recommendations: string[]
  signals: Record<string, number>
  weak_story_ids: string[]
  // The three review agents' own raw scores, alongside the two blended
  // headline scores above — one per Key Findings category.
  source_material_score: number
  stories_score: number
  advisory_content_score: number
  created_at: string
  updated_at: string
}

export interface RequirementsDetail {
  document: Document
  epics: RequirementItem[]
  stories: RequirementItem[]
  gaps: Gap[]
  unresolved_gap_count: number
  suggestions: RequirementItem[] // pending ai_suggestion items only
  // null until the PM runs an on-demand evaluation — never computed automatically.
  evaluation: EvaluationReport | null
}

// Shared shape for create/update item payloads — every field optional so one
// type covers epic-title-only renames, epic assumptions/dependencies edits,
// and full story edits (text/description/scenarios/AC/error_handling).
export interface ItemFields {
  text?: string
  description?: string
  scenarios?: Scenario[]
  acceptance_criteria?: AcceptanceCriterion[]
  error_handling?: ErrorHandlingEntry[]
  assumptions?: string[]
  dependencies?: string[]
  source_reference?: string // epics only
  origin?: ItemOrigin // set to 'pm_ai_assisted' when confirming a generated draft
}

// Response shapes from POST .../items/generate-draft — which fields are
// present depends on `kind` in the request.
export interface EpicDraft {
  title: string
  assumptions: string[]
  dependencies: string[]
}

export interface StoryDraft {
  title: string
  description: string
  scenarios: Scenario[]
  acceptance_criteria: AcceptanceCriterion[]
  error_handling: ErrorHandlingEntry[]
}

export interface AcDraft {
  text: string
  out_of_scope: boolean
}

// The shape of a generate-draft response varies by kind — this covers all
// of them for the `previous_draft` regenerate parameter, where the caller
// just passes back whatever the last response was without needing to know
// which specific shape it is.
export type ItemDraft = EpicDraft | StoryDraft | AcDraft | Scenario | ErrorHandlingEntry

export interface TextIngestResponse {
  document: Document
  epics_extracted: number
  stories_extracted: number
  gaps_found: number
}

export interface ChangeRequestIngestResponse {
  change_request_document: Document
  requirements_document: Document
  epics_extracted: number
  stories_extracted: number
  gaps_found: number
}

// The shape of Document.type_metadata.confluence, once a version has been published.
export interface ConfluencePublishInfo {
  page_id: string
  page_url: string
  published_at: string
}

export interface ConfluencePublishResponse {
  document: Document
  page_id: string
  page_url: string
}

export interface BoundingBox {
  top: number
  left: number
  bottom: number
  right: number
}

export interface AlignmentFinding {
  id: string
  requirement_item_id: string | null
  requirement_external_id: string | null
  issue: string
  recommendation: string
  bounding_box: BoundingBox | null
  resolution_status: FindingStatus
}

export interface AlignmentReport {
  id: string
  page: number
  status: AlignmentStatus
  findings: AlignmentFinding[]
}

export interface DesignDetail {
  document: Document
  requirements_document_id: string | null
  reports: AlignmentReport[]
}

export interface DesignIngestResponse {
  document: Document
  pages_indexed: number
  screens_checked: number
  aligned_count: number
  partial_count: number
  misaligned_count: number
}

export interface IntakeResource {
  id: string
  project_id: string
  resource_kind: IntakeResourceKind
  original_filename: string
  file_type: IntakeFileType
  extracted_text: string | null
  processing_error: string | null
  notes: string | null
  uploaded_at: string
}

export interface ClarifyingQuestion {
  id: string
  project_id: string
  question_text: string
  topic_area: string | null
  why_it_matters: string | null
  status: ClarifyingQuestionStatus
  answer_text: string | null
  created_at: string
  answered_at: string | null
}

export interface StandingPolicy {
  id: string
  title: string
  policy_text: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface PolicyDraft {
  title: string
  policy_text: string
}
