import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { DesignDetail, Project, RequirementsDetail } from '../api/types'
import { plural } from '../lib/format'
import { summarizeAlignment } from '../lib/design'
import {
  confluenceInfo,
  currentStepIndex,
  deriveSteps,
  isApproved,
  nextAction,
  stageLabel,
  type LifecycleStep,
  type NextAction,
} from '../lib/lifecycle'

export interface ProjectSummary {
  project: Project
  resourceCount: number
  requirements: RequirementsDetail | null
  design: DesignDetail | null
  steps: LifecycleStep[]
  stepIndex: number
  next: NextAction
  stage: string
  published: boolean
  /** Latest timestamp we know of for the project (ISO, UTC). */
  updatedAt: string
}

export interface ActivityEvent {
  id: string
  at: string
  icon: 'check' | 'eye' | 'send'
  projectId: string
  subject: string
  detail: string
}

/** A project that fails to load a piece (or simply has none yet) still gets a card. */
async function optional<T>(request: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await request()
  } catch {
    return fallback
  }
}

/**
 * One summary per project, composed from the existing per-project endpoints.
 * (A dedicated summary endpoint would save requests; with a handful of
 * projects the extra calls are cheap and need no backend change.)
 */
export function useProjectSummaries(projects: Project[]) {
  const [summaries, setSummaries] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)

  const key = projects.map((p) => p.id).join(',')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all(
      projects.map(async (project): Promise<ProjectSummary> => {
        const [resources, requirements] = await Promise.all([
          optional(() => api.listIntakeResources(project.id), []),
          optional(() => api.getLatestRequirements(project.id), null),
        ])
        // A design is only checked against an approved version, so don't ask before one exists.
        const design = isApproved(requirements) ? await optional(() => api.getLatestDesign(project.id), null) : null
        const facts = { resourceCount: resources.length, requirements, design, generating: false }
        const timestamps = [
          project.created_at,
          requirements?.document.uploaded_at,
          design?.document.uploaded_at,
          ...resources.map((r) => r.uploaded_at),
        ].filter((t): t is string => Boolean(t))
        return {
          project,
          resourceCount: resources.length,
          requirements,
          design,
          steps: deriveSteps(facts),
          stepIndex: currentStepIndex(facts),
          next: nextAction(facts),
          stage: stageLabel(facts),
          published: Boolean(confluenceInfo(requirements)),
          updatedAt: timestamps.sort().at(-1) ?? project.created_at,
        }
      }),
    ).then((result) => {
      if (cancelled) return
      setSummaries(result)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
    // `key` stands in for the project list identity
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return { summaries, loading }
}

/** Newest-first feed of things that happened, built from document timestamps. */
export function buildActivity(summaries: Pick<ProjectSummary, 'project' | 'requirements' | 'design'>[]): ActivityEvent[] {
  const events: ActivityEvent[] = []

  for (const s of summaries) {
    const { requirements, design, project } = s
    if (requirements) {
      const gaps = requirements.unresolved_gap_count
      events.push({
        id: `${project.id}-req`,
        at: requirements.document.uploaded_at,
        icon: 'check',
        projectId: project.id,
        subject: `Requirements v${requirements.document.version}`,
        detail: `generated for ${project.name}${gaps > 0 ? ` · ${plural(gaps, 'gap')} found` : ''}`,
      })
      const published = confluenceInfo(requirements)
      if (published) {
        events.push({
          id: `${project.id}-pub`,
          at: published.published_at,
          icon: 'send',
          projectId: project.id,
          subject: project.name,
          detail: `published to Confluence · v${requirements.document.version}`,
        })
      }
    }
    if (design) {
      const { percent } = summarizeAlignment(design.reports)
      events.push({
        id: `${project.id}-design`,
        at: design.document.uploaded_at,
        icon: 'eye',
        projectId: project.id,
        subject: 'Design check',
        detail: `finished for ${project.name} · ${percent}% aligned`,
      })
    }
  }

  return events.sort((a, b) => b.at.localeCompare(a.at))
}

/** Projects that need a person's decision, most urgent first. */
export function useAttentionItems(summaries: ProjectSummary[]) {
  return useMemo(() => {
    const items: { summary: ProjectSummary; tone: 'warning' | 'info'; badge: string; text: string }[] = []
    for (const s of summaries) {
      const { requirements, design } = s
      if (requirements && !isApproved(requirements) && requirements.unresolved_gap_count > 0) {
        items.push({
          summary: s,
          tone: 'warning',
          badge: plural(requirements.unresolved_gap_count, 'gap'),
          text: 'resolve gaps before approving',
        })
      } else if (requirements && isApproved(requirements) && design) {
        const needLook = design.reports.filter((r) => r.status !== 'aligned').length
        if (needLook > 0) {
          items.push({ summary: s, tone: 'info', badge: 'Review', text: `${plural(needLook, 'screen')} need a look` })
        }
      }
    }
    return items
  }, [summaries])
}
