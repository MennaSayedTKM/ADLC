import type {
  DevOverview,
  JiraPreviewData,
  JiraSendResult,
  DevStory,
  DevTask,
  TechDocumentRead,
  TechProfile,
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
  ReferenceStyle,
  StyleBrief,
  TextIngestResponse,
  UxPrompt,
  UxPromptMode,
  UxPromptSources,
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

const UNREACHABLE = 'We couldn’t reach the server. Check your connection and try again.'
const UNRESPONSIVE = 'The server isn’t responding right now. Please try again in a moment.'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isForm = options.body instanceof FormData
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...options,
      headers: isForm ? options.headers : { 'Content-Type': 'application/json', ...options.headers },
    })
  } catch {
    // fetch only rejects when no response arrived at all (offline, server down)
    throw new ApiError(0, UNREACHABLE)
  }

  if (!res.ok) {
    // A bare gateway status ("Bad Gateway") means the server never answered; say that in plain words.
    let detail = [502, 503, 504].includes(res.status) ? UNRESPONSIVE : res.statusText || `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data?.detail === 'string') detail = data.detail // the server's own explanation wins
    } catch {
      // response wasn't JSON — keep the fallback above
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

  getUxPromptSources: (projectId: string) =>
    request<UxPromptSources>(`/projects/${projectId}/ux-prompts/sources`),
  workOutDependencies: (projectId: string) =>
    request<UxPromptSources>(`/projects/${projectId}/ux-prompts/dependencies`, { method: 'POST' }),

  listUxPrompts: (projectId: string) => request<UxPrompt[]>(`/projects/${projectId}/ux-prompts`),

  saveStyleBrief: (projectId: string, body: StyleBrief) =>
    request<StyleBrief>(`/projects/${projectId}/ux-prompts/style-brief`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  extractStyleReference: (projectId: string, url: string) =>
    request<ReferenceStyle>(`/projects/${projectId}/ux-prompts/style-references/extract`, {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),

  draftVision: (projectId: string) =>
    request<{ vision: string; target_users: string }>(`/projects/${projectId}/ux-prompts/vision/draft`, {
      method: 'POST',
    }),

  // mode 'foundation' is the platform blueprint: no epic or stories.
  generateUxPrompt: (
    projectId: string,
    body: {
      documentId: string
      mode: UxPromptMode
      styleBrief: StyleBrief
      epicId?: string
      storyIds?: string[]
      screenshot?: File | null
    },
  ) => {
    const form = new FormData()
    form.append('document_id', body.documentId)
    form.append('mode', body.mode)
    form.append('style_brief', JSON.stringify(body.styleBrief))
    if (body.epicId) form.append('epic_id', body.epicId)
    form.append('story_ids', JSON.stringify(body.storyIds ?? []))
    if (body.screenshot) form.append('screenshot', body.screenshot)
    return request<UxPrompt>(`/projects/${projectId}/ux-prompts`, { method: 'POST', body: form })
  },

  regenerateUxPrompt: (projectId: string, promptId: string) =>
    request<UxPrompt>(`/projects/${projectId}/ux-prompts/${promptId}/regenerate`, { method: 'POST' }),

  // editedText null resets to the generated text
  updateUxPrompt: (projectId: string, promptId: string, editedText: string | null) =>
    request<UxPrompt>(`/projects/${projectId}/ux-prompts/${promptId}`, {
      method: 'PATCH',
      body: JSON.stringify({ edited_text: editedText }),
    }),

  deleteUxPrompt: (projectId: string, promptId: string) =>
    request<void>(`/projects/${projectId}/ux-prompts/${promptId}`, { method: 'DELETE' }),

  // Development stories
  getDevOverview: (projectId: string) => request<DevOverview>(`/projects/${projectId}/dev-stories`),
  saveTechProfile: (projectId: string, areas: Record<string, string>) =>
    request<TechProfile>(`/projects/${projectId}/dev-stories/tech-profile`, {
      method: 'PUT',
      body: JSON.stringify({ areas }),
    }),
  readTechDocument: (projectId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<TechDocumentRead>(`/projects/${projectId}/dev-stories/tech-profile/document`, {
      method: 'POST',
      body: form,
    })
  },
  generateDevStories: (projectId: string, epicExternalId: string) =>
    request<DevStory[]>(`/projects/${projectId}/dev-stories/epics/${epicExternalId}/generate`, { method: 'POST' }),
  updateDevStory: (projectId: string, storyId: string, changes: Partial<Pick<DevStory, 'title' | 'description' | 'acceptance_criteria' | 'story_points' | 'labels'>>) =>
    request<DevStory>(`/projects/${projectId}/dev-stories/stories/${storyId}`, {
      method: 'PATCH',
      body: JSON.stringify(changes),
    }),
  deleteDevStory: (projectId: string, storyId: string) =>
    request<void>(`/projects/${projectId}/dev-stories/stories/${storyId}`, { method: 'DELETE' }),
  updateDevTask: (projectId: string, taskId: string, changes: Partial<Pick<DevTask, 'title' | 'summary' | 'area' | 'edited_prompt'>>) =>
    request<DevTask>(`/projects/${projectId}/dev-stories/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify(changes),
    }),
  deleteDevTask: (projectId: string, taskId: string) =>
    request<void>(`/projects/${projectId}/dev-stories/tasks/${taskId}`, { method: 'DELETE' }),
  writeCodingPrompt: (projectId: string, taskId: string) =>
    request<DevTask>(`/projects/${projectId}/dev-stories/tasks/${taskId}/coding-prompt`, { method: 'POST' }),

  // Jira (development stories). Only sendEpicToJira writes to Jira.
  getJiraPreview: (projectId: string) => request<JiraPreviewData>(`/projects/${projectId}/dev-stories/jira`),
  connectJiraProject: (projectId: string, projectKey: string) =>
    request<JiraPreviewData>(`/projects/${projectId}/dev-stories/jira/settings`, {
      method: 'PUT',
      body: JSON.stringify({ project_key: projectKey }),
    }),
  getJiraDefault: () => request<{ default_project_key: string | null }>('/settings/jira'),
  saveJiraDefault: (defaultProjectKey: string) =>
    request<{ default_project_key: string | null }>('/settings/jira', {
      method: 'PUT',
      body: JSON.stringify({ default_project_key: defaultProjectKey }),
    }),
  sendEpicToJira: (projectId: string, epicExternalId: string) =>
    request<JiraSendResult>(`/projects/${projectId}/dev-stories/jira/epics/${epicExternalId}/send`, { method: 'POST' }),
}
