import { useEffect, useState } from 'react'
import './App.css'
import { api } from './api/client'
import type { Project } from './api/types'
import type { Module } from './components/ProjectBar'
import { ProjectBar } from './components/ProjectBar'
import { Banner } from './components/ui/Banner'
import { DesignReviewPage } from './pages/DesignReviewPage'
import { RequirementsReviewPage } from './pages/RequirementsReviewPage'
import { StandingPoliciesPage } from './pages/StandingPoliciesPage'

const LAST_PROJECT_KEY = 'tkmind:lastProjectId'

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [activeModule, setActiveModule] = useState<Module>('requirements')
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    api
      .listProjects()
      .then((list) => {
        setProjects(list)
        const remembered = localStorage.getItem(LAST_PROJECT_KEY)
        const stillExists = remembered && list.some((p) => p.id === remembered)
        setSelectedProjectId(stillExists ? remembered : (list[0]?.id ?? null))
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load projects'))
      .finally(() => setLoaded(true))
  }, [])

  function handleSelect(projectId: string) {
    setSelectedProjectId(projectId)
    localStorage.setItem(LAST_PROJECT_KEY, projectId)
  }

  async function handleCreate(name: string) {
    const project = await api.createProject(name)
    setProjects((prev) => [project, ...prev])
    handleSelect(project.id)
  }

  return (
    <div className="app">
      <ProjectBar
        projects={projects}
        selectedProjectId={selectedProjectId}
        onSelect={handleSelect}
        onCreate={handleCreate}
        activeModule={activeModule}
        onModuleChange={setActiveModule}
      />

      <main className="app__main">
        {error && (
          <div className="app__banner">
            <Banner tone="danger">{error}</Banner>
          </div>
        )}

        {!error && activeModule === 'policies' && <StandingPoliciesPage />}

        {!error && activeModule !== 'policies' && loaded && projects.length === 0 && (
          <div className="app__empty-state">
            <p>No projects yet. Create one above to get started.</p>
          </div>
        )}

        {!error && selectedProjectId && activeModule === 'requirements' && (
          <RequirementsReviewPage projectId={selectedProjectId} />
        )}
        {!error && selectedProjectId && activeModule === 'design' && (
          <DesignReviewPage projectId={selectedProjectId} />
        )}
      </main>
    </div>
  )
}

export default App
