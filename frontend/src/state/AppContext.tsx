import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Project } from '../api/types'

interface AppState {
  projects: Project[]
  loaded: boolean
  error: string | null
  createProject: (name: string) => Promise<Project>
  reloadProjects: () => Promise<void>
}

const AppContext = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reloadProjects = useCallback(async () => {
    try {
      setProjects(await api.listProjects())
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load projects')
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    reloadProjects()
  }, [reloadProjects])

  const createProject = useCallback(async (name: string) => {
    const project = await api.createProject(name)
    setProjects((prev) => [project, ...prev])
    return project
  }, [])

  const value = useMemo(
    () => ({ projects, loaded, error, createProject, reloadProjects }),
    [projects, loaded, error, createProject, reloadProjects],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>')
  return ctx
}
