import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, ApiError } from '../api/client'
import type { DesignDetail, IntakeResource, Project, RequirementsDetail } from '../api/types'
import { deriveSteps, nextAction, type LifecycleStep, type NextAction } from '../lib/lifecycle'

export type GenerationState =
  | { status: 'idle' }
  | { status: 'running'; startedAt: number }
  | { status: 'failed'; error: string }

interface ProjectState {
  project: Project
  /** `undefined` while loading, `null` when the project has none yet. */
  resources: IntakeResource[] | undefined
  requirements: RequirementsDetail | null | undefined
  design: DesignDetail | null | undefined
  /** False until sources, requirements and design have all answered — before that the lifecycle is a guess. */
  ready: boolean
  steps: LifecycleStep[]
  next: NextAction
  generation: GenerationState
  /** A design check in progress; like `generation`, it keeps running if the person leaves the page. */
  validation: GenerationState
  setResources: (updater: (prev: IntakeResource[]) => IntakeResource[]) => void
  setRequirements: (detail: RequirementsDetail) => void
  setDesign: (detail: DesignDetail) => void
  reloadResources: () => Promise<void>
  reloadRequirements: () => Promise<void>
  reloadDesign: () => Promise<void>
  /**
   * Starts extraction and keeps it running if the user navigates to another
   * page of the project — the request lives here, not in the Sources page.
   */
  generateRequirements: () => Promise<void>
  clearGenerationError: () => void
  /** Uploads exported screens and checks each against the approved requirements. */
  runValidation: (file: File) => Promise<void>
  clearValidationError: () => void
}

const ProjectContext = createContext<ProjectState | null>(null)

async function loadOptional<T>(request: () => Promise<T>): Promise<T | null> {
  try {
    return await request()
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null // nothing there yet — not an error
    throw err
  }
}

export function ProjectProvider({ project, children }: { project: Project; children: ReactNode }) {
  const [resources, setResourcesState] = useState<IntakeResource[] | undefined>(undefined)
  const [requirements, setRequirements] = useState<RequirementsDetail | null | undefined>(undefined)
  const [design, setDesign] = useState<DesignDetail | null | undefined>(undefined)
  const [generation, setGeneration] = useState<GenerationState>({ status: 'idle' })
  const [validation, setValidation] = useState<GenerationState>({ status: 'idle' })
  const projectId = project.id
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const reloadResources = useCallback(async () => {
    setResourcesState(await api.listIntakeResources(projectId).catch(() => []))
  }, [projectId])

  const reloadRequirements = useCallback(async () => {
    setRequirements(await loadOptional(() => api.getLatestRequirements(projectId)).catch(() => null))
  }, [projectId])

  const reloadDesign = useCallback(async () => {
    setDesign(await loadOptional(() => api.getLatestDesign(projectId)).catch(() => null))
  }, [projectId])

  useEffect(() => {
    reloadResources()
    reloadRequirements()
    reloadDesign()
  }, [reloadResources, reloadRequirements, reloadDesign])

  const generateRequirements = useCallback(async () => {
    setGeneration({ status: 'running', startedAt: Date.now() })
    try {
      await api.runStagedExtraction(projectId)
      await Promise.all([reloadRequirements(), reloadResources()])
      if (mounted.current) setGeneration({ status: 'idle' })
    } catch (err) {
      if (mounted.current) {
        setGeneration({
          status: 'failed',
          error: err instanceof Error ? err.message : 'Generating requirements failed',
        })
      }
    }
  }, [projectId, reloadRequirements, reloadResources])

  const runValidation = useCallback(
    async (file: File) => {
      setValidation({ status: 'running', startedAt: Date.now() })
      try {
        await api.uploadDesign(projectId, file)
        await reloadDesign()
        if (mounted.current) setValidation({ status: 'idle' })
      } catch (err) {
        if (mounted.current) {
          setValidation({ status: 'failed', error: err instanceof Error ? err.message : 'Checking the design failed' })
        }
      }
    },
    [projectId, reloadDesign],
  )

  const setResources = useCallback((updater: (prev: IntakeResource[]) => IntakeResource[]) => {
    setResourcesState((prev) => updater(prev ?? []))
  }, [])

  const clearGenerationError = useCallback(() => setGeneration({ status: 'idle' }), [])
  const clearValidationError = useCallback(() => setValidation({ status: 'idle' }), [])

  const facts = useMemo(
    () => ({
      resourceCount: resources?.length ?? 0,
      requirements: requirements ?? null,
      design: design ?? null,
      generating: generation.status === 'running',
    }),
    [resources, requirements, design, generation.status],
  )

  const value = useMemo<ProjectState>(
    () => ({
      project,
      resources,
      requirements,
      design,
      ready: resources !== undefined && requirements !== undefined && design !== undefined,
      steps: deriveSteps(facts),
      next: nextAction(facts),
      generation,
      validation,
      setResources,
      setRequirements: (detail) => setRequirements(detail),
      setDesign: (detail) => setDesign(detail),
      reloadResources,
      reloadRequirements,
      reloadDesign,
      generateRequirements,
      clearGenerationError,
      runValidation,
      clearValidationError,
    }),
    [
      project,
      resources,
      requirements,
      design,
      facts,
      generation,
      validation,
      setResources,
      reloadResources,
      reloadRequirements,
      reloadDesign,
      generateRequirements,
      clearGenerationError,
      runValidation,
      clearValidationError,
    ],
  )

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

export function useProject(): ProjectState {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProject must be used inside <ProjectProvider>')
  return ctx
}

/** For shell pieces that render both inside and outside a project. */
export function useOptionalProject(): ProjectState | null {
  return useContext(ProjectContext)
}
