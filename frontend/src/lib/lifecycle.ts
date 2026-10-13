import type { ConfluencePublishInfo, DesignDetail, RequirementsDetail } from '../api/types'
import { plural } from './format'
import type { ProjectPage } from './router'

/**
 * The six-step lifecycle shown in the stepper. Nothing here is stored: every
 * step is derived from what already exists for the project (sources, the
 * latest requirements version, the latest design check), so it can never
 * drift from reality.
 */

export type StepId = 'sources' | 'generate' | 'review' | 'approve' | 'design' | 'publish'
export type StepState = 'done' | 'current' | 'upcoming'

export interface LifecycleFacts {
  resourceCount: number
  requirements: RequirementsDetail | null
  design: DesignDetail | null
  generating: boolean
}

export interface LifecycleStep {
  id: StepId
  number: number
  title: string
  subtitle: string
  page: ProjectPage
  state: StepState
}

const STEP_DEFS: Omit<LifecycleStep, 'state'>[] = [
  { id: 'sources', number: 1, title: 'Add sources', subtitle: 'Your documents', page: 'sources' },
  { id: 'generate', number: 2, title: 'Generate', subtitle: 'Stories & diagrams', page: 'sources' },
  { id: 'review', number: 3, title: 'Review', subtitle: 'Fix gaps', page: 'requirements' },
  { id: 'approve', number: 4, title: 'Approve', subtitle: 'Lock a version', page: 'requirements' },
  { id: 'design', number: 5, title: 'Design', subtitle: 'Screens & check', page: 'design' },
  { id: 'publish', number: 6, title: 'Publish', subtitle: 'PDF · Confluence', page: 'publish' },
]

export function isApproved(requirements: RequirementsDetail | null | undefined): boolean {
  return requirements?.document.approval_status === 'approved'
}

export function confluenceInfo(requirements: RequirementsDetail | null): ConfluencePublishInfo | undefined {
  return requirements?.document.type_metadata?.confluence as ConfluencePublishInfo | undefined
}

/** Screens that only partly match the requirements and still have an unresolved finding. */
export function screensNeedingAttention(design: DesignDetail | null): number {
  if (!design) return 0
  return design.reports.filter(
    (r) => r.status !== 'aligned' && r.findings.some((f) => f.resolution_status === 'open'),
  ).length
}

/**
 * Index (0–5) of the step the user is on, or 6 when everything is finished.
 * The Design step stays current until every screen is aligned or its findings
 * are resolved — uploading screens is the start of that work, not the end.
 */
export function currentStepIndex(facts: LifecycleFacts): number {
  const { requirements, design, generating } = facts
  if (!requirements) return generating ? 1 : 0
  if (!isApproved(requirements)) return 2
  if (!design || screensNeedingAttention(design) > 0) return 4
  return confluenceInfo(requirements) ? 6 : 5
}

/** Short task-language description of where a project is, for cards and lists. */
export function stageLabel(facts: LifecycleFacts): string {
  const index = currentStepIndex(facts)
  if (index >= 6) return 'Published to Confluence'
  const step = deriveSteps(facts)[index]
  const names = [
    'Add sources',
    'Generating requirements',
    'Review requirements',
    'Approve requirements',
    facts.design ? 'Design check' : 'Design',
    'Publish',
  ]
  return `Step ${step.number} of ${STEP_DEFS.length} · ${names[index]}`
}

export function deriveSteps(facts: LifecycleFacts): LifecycleStep[] {
  const current = currentStepIndex(facts)
  return STEP_DEFS.map((def, index) => ({
    ...def,
    state: index < current ? 'done' : index === current ? 'current' : 'upcoming',
  }))
}

export interface NextAction {
  title: string
  body: string
  label: string
  page: ProjectPage
  query?: Record<string, string>
}

/** The single next best action for a project — drives the sidebar guide and the overview hero. */
export function nextAction(facts: LifecycleFacts): NextAction {
  const { resourceCount, requirements, design, generating } = facts

  if (!requirements) {
    if (generating) {
      return {
        title: 'Generating your requirements',
        body: 'This runs in the background — you can leave this page and come back.',
        label: 'See progress',
        page: 'sources',
      }
    }
    if (resourceCount === 0) {
      return {
        title: 'Add your first source',
        body: 'Drop a requirements document, meeting notes or a whiteboard photo.',
        label: 'Add sources',
        page: 'sources',
      }
    }
    return {
      title: 'Generate your requirements',
      body: `${plural(resourceCount, 'source')} added. We'll draft the stories and flag any gaps.`,
      label: 'Review sources',
      page: 'sources',
    }
  }

  if (!isApproved(requirements)) {
    const gaps = requirements.unresolved_gap_count
    if (gaps > 0) {
      return {
        title: `Resolve ${plural(gaps, 'open gap')}`,
        body: 'Fix or dismiss each gap, then approve this version to unlock design.',
        label: 'Resolve gaps',
        page: 'requirements',
        query: { tab: 'gaps' },
      }
    }
    return {
      title: 'Approve this version',
      body: `Version ${requirements.document.version} has no open gaps. Approving locks it so designs can't drift.`,
      label: 'Review & approve',
      page: 'requirements',
    }
  }

  if (!design) {
    return {
      title: 'Create your design prompts',
      body: 'Turn the approved stories into prompts for Figma Make, then check the result here.',
      label: 'Open design prompts',
      page: 'design',
    }
  }

  const needAttention = screensNeedingAttention(design)
  if (needAttention > 0) {
    return {
      title: `${plural(needAttention, 'screen')} need a look`,
      body: 'Some screens only partly match the approved requirements.',
      label: 'Review findings',
      page: 'validate',
    }
  }

  if (!confluenceInfo(requirements)) {
    return {
      title: 'Publish your work',
      body: 'Export a PDF or publish the approved version to Confluence.',
      label: 'Publish & export',
      page: 'publish',
    }
  }

  return {
    title: 'Everything is published',
    body: 'Re-open any step if the requirements change.',
    label: 'View history',
    page: 'publish',
  }
}
