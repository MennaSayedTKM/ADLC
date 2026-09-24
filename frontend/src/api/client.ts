import type {
  AcDraft,
  ChangeRequestIngestResponse,
  ConfluencePublishResponse,
  CrRequestType,
  ClarifyingQuestion,
  ClarifyingQuestionStatus,
  DesignDetail,
  DesignIngestResponse,
  Document,
  DraftKind,
  ErrorHandlingEntry,
  EpicDraft,
  IntakeResource,
  IntakeResourceKind,
  ItemDraft,
  ItemFields,
  PolicyDraft,
  Project,
  RequirementsDetail,
  Scenario,
  StandingPolicy,
  StoryDraft,
  TextIngestResponse,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isForm = options.body instanceof FormData
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: isForm ? options.headers : { 'Content-Type': 'application/json', ...options.headers },
  })

  if (!res.ok) {
    let detail = res.statusText || `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data?.detail === 'string') detail = data.detail
    } catch {
      // response wasn't JSON — fall back to statusText
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  listProjects: () => request<Project[]>('/projects'),

  createProject: (name: string) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify({ name }) }),

  getLatestRequirements: (projectId: string) =>
    request<RequirementsDetail>(`/projects/${projectId}/requirements`),

  getRequirementsVersion: (projectId: string, docId: string) =>
    request<RequirementsDetail>(`/projects/${projectId}/requirements/${docId}`),

  uploadRequirements: (projectId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<TextIngestResponse>(`/projects/${projectId}/requirements`, {
      method: 'POST',
      body: form,
    })
  },

  runStagedExtraction: (projectId: string) =>
    request<TextIngestResponse>(`/projects/${projectId}/requirements/run-staged-extraction`, {
      method: 'POST',
    }),

  updateItem: (projectId: string, docId: string, itemId: string, body: ItemFields) =>
    request<RequirementsDetail>(`/projects/${projectId}/requirements/${docId}/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  createItem: (
    projectId: string,
    docId: string,
    body: ItemFields & { type: 'epic' | 'story'; text: string; parent_id?: string },
  ) =>
    request<RequirementsDetail>(`/projects/${projectId}/requirements/${docId}/items`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  generateItemDraft: (
    projectId: string,
    docId: string,
    body: { kind: DraftKind; subject: string; parent_id?: string; previous_draft?: ItemDraft },
  ) => {
    const path = `/projects/${projectId}/requirements/${docId}/items/generate-draft`
    if (body.kind === 'epic') return request<EpicDraft>(path, { method: 'POST', body: JSON.stringify(body) })
    if (body.kind === 'story') return request<StoryDraft>(path, { method: 'POST', body: JSON.stringify(body) })
    if (body.kind === 'acceptance_criterion') return request<AcDraft>(path, { method: 'POST', body: JSON.stringify(body) })
    if (body.kind === 'scenario') return request<Scenario>(path, { method: 'POST', body: JSON.stringify(body) })
    return request<ErrorHandlingEntry>(path, { method: 'POST', body: JSON.stringify(body) })
  },

  deleteItem: (projectId: string, docId: string, itemId: string) =>
    request<RequirementsDetail>(`/projects/${projectId}/requirements/${docId}/items/${itemId}`, {
      method: 'DELETE',
    }),

  acceptSuggestion: (projectId: string, docId: string, itemId: string) =>
    request<RequirementsDetail>(
      `/projects/${projectId}/requirements/${docId}/suggestions/${itemId}/accept`,
      { method: 'POST' },
    ),

  dismissSuggestion: (projectId: string, docId: string, itemId: string) =>
    request<RequirementsDetail>(
      `/projects/${projectId}/requirements/${docId}/suggestions/${itemId}/dismiss`,
      { method: 'POST' },
    ),

  // 'resolved' isn't accepted here — the backend requires resolving a gap
  // through resolveGapAsStory() instead, so a story always exists behind a
  // resolved gap. This only covers dismiss ('dismissed') / reopen ('open').
  updateGapStatus: (projectId: string, docId: string, gapId: string, status: 'dismissed' | 'open') =>
    request<RequirementsDetail>(`/projects/${projectId}/requirements/${docId}/gaps/${gapId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),

  resolveGapAsStory: (
    projectId: string,
    docId: string,
    gapId: string,
    body: { parent_id: string } & ItemFields,
  ) =>
    request<RequirementsDetail>(
      `/projects/${projectId}/requirements/${docId}/gaps/${gapId}/resolve-as-story`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  approve: (projectId: string, docId: string) =>
    request<Document>(`/projects/${projectId}/requirements/${docId}/approve`, {
      method: 'POST',
    }),

  runEvaluation: (projectId: string, docId: string) =>
    request<RequirementsDetail>(`/projects/${projectId}/requirements/${docId}/evaluate`, {
      method: 'POST',
    }),

  uploadChangeRequest: (
    projectId: string,
    file: File,
    body: { request_type: CrRequestType; classification?: string; estimated_effort?: string; estimated_cost?: string },
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('request_type', body.request_type)
    if (body.classification) form.append('classification', body.classification)
    if (body.estimated_effort) form.append('estimated_effort', body.estimated_effort)
    if (body.estimated_cost) form.append('estimated_cost', body.estimated_cost)
    return request<ChangeRequestIngestResponse>(`/projects/${projectId}/requirements/change-requests`, {
      method: 'POST',
      body: form,
    })
  },

  // 'business': stakeholder-facing business requirements document.
  // 'delivery': epics/stories with scenarios and error handling, for the delivery team.
  exportPdfUrl: (projectId: string, docId: string, format: 'business' | 'delivery' = 'business') =>
    `${BASE}/projects/${projectId}/requirements/${docId}/export.pdf?format=${format}`,

  publishToConfluence: (projectId: string, docId: string) =>
    request<ConfluencePublishResponse>(
      `/projects/${projectId}/requirements/${docId}/publish-confluence`,
      { method: 'POST' },
    ),

  getLatestDesign: (projectId: string) => request<DesignDetail>(`/projects/${projectId}/designs`),

  getDesignAlignment: (projectId: string, docId: string) =>
    request<DesignDetail>(`/projects/${projectId}/designs/${docId}/alignment`),

  uploadDesign: (projectId: string, file: File, requirementsDocumentId?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (requirementsDocumentId) form.append('requirements_document_id', requirementsDocumentId)
    return request<DesignIngestResponse>(`/projects/${projectId}/designs`, {
      method: 'POST',
      body: form,
    })
  },

  updateFindingStatus: (projectId: string, docId: string, findingId: string, status: string) =>
    request<DesignDetail>(`/projects/${projectId}/designs/${docId}/findings/${findingId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),

  screenImageUrl: (projectId: string, docId: string, page: number) =>
    `${BASE}/projects/${projectId}/designs/${docId}/screens/${page}/image`,

  listIntakeResources: (projectId: string) =>
    request<IntakeResource[]>(`/projects/${projectId}/resources`),

  uploadIntakeResource: (
    projectId: string,
    file: File,
    resourceKind: IntakeResourceKind,
    notes?: string,
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('resource_kind', resourceKind)
    if (notes) form.append('notes', notes)
    return request<IntakeResource>(`/projects/${projectId}/resources`, {
      method: 'POST',
      body: form,
    })
  },

  deleteIntakeResource: (projectId: string, resourceId: string) =>
    request<void>(`/projects/${projectId}/resources/${resourceId}`, { method: 'DELETE' }),

  generateClarifyingQuestions: (projectId: string) =>
    request<ClarifyingQuestion[]>(`/projects/${projectId}/clarifying-questions`, { method: 'POST' }),

  listClarifyingQuestions: (projectId: string) =>
    request<ClarifyingQuestion[]>(`/projects/${projectId}/clarifying-questions`),

  updateClarifyingQuestion: (
    projectId: string,
    questionId: string,
    body: { status: ClarifyingQuestionStatus; answer_text?: string },
  ) =>
    request<ClarifyingQuestion>(`/projects/${projectId}/clarifying-questions/${questionId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  listPolicies: () => request<StandingPolicy[]>('/policies'),

  createPolicy: (title: string, policyText: string) =>
    request<StandingPolicy>('/policies', {
      method: 'POST',
      body: JSON.stringify({ title, policy_text: policyText }),
    }),

  updatePolicy: (
    policyId: string,
    body: { title?: string; policy_text?: string; is_active?: boolean },
  ) =>
    request<StandingPolicy>(`/policies/${policyId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  generatePolicyDraft: (subject: string, previousDraft?: PolicyDraft) =>
    request<PolicyDraft>('/policies/generate-draft', {
      method: 'POST',
      body: JSON.stringify({ subject, previous_draft: previousDraft }),
    }),
}
