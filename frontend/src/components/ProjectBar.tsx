import { useState } from 'react'
import type { Project } from '../api/types'
import { Button } from './ui/Button'
import './ProjectBar.css'

export type Module = 'requirements' | 'design' | 'policies'

interface ProjectBarProps {
  projects: Project[]
  selectedProjectId: string | null
  onSelect: (projectId: string) => void
  onCreate: (name: string) => Promise<void>
  activeModule: Module
  onModuleChange: (module: Module) => void
}

export function ProjectBar({
  projects,
  selectedProjectId,
  onSelect,
  onCreate,
  activeModule,
  onModuleChange,
}: ProjectBarProps) {
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onCreate(name.trim())
      setName('')
      setCreating(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create project')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="project-bar">
      <div className="project-bar__brand">
        <span className="project-bar__mark">TK</span>
        <span className="project-bar__title">TKMiND</span>
        <span className="project-bar__divider" />
        <nav className="project-bar__tabs">
          <button
            type="button"
            className={`project-bar__tab ${activeModule === 'requirements' ? 'project-bar__tab--active' : ''}`}
            onClick={() => onModuleChange('requirements')}
          >
            Requirements
          </button>
          <button
            type="button"
            className={`project-bar__tab ${activeModule === 'design' ? 'project-bar__tab--active' : ''}`}
            onClick={() => onModuleChange('design')}
          >
            Design Review
          </button>
        </nav>
      </div>

      <div className="project-bar__controls">
        <button
          type="button"
          className={`project-bar__policies-link ${activeModule === 'policies' ? 'project-bar__policies-link--active' : ''}`}
          onClick={() => onModuleChange('policies')}
        >
          Policies
        </button>

        {!creating && (
          <>
            <select
              className="project-bar__select"
              value={selectedProjectId ?? ''}
              onChange={(e) => onSelect(e.target.value)}
              disabled={projects.length === 0}
            >
              {projects.length === 0 && <option value="">No projects yet</option>}
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <Button variant="secondary" size="sm" onClick={() => setCreating(true)}>
              + New project
            </Button>
          </>
        )}

        {creating && (
          <form className="project-bar__create-form" onSubmit={handleCreate}>
            <input
              autoFocus
              className="project-bar__input"
              placeholder="Project name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
            />
            <Button type="submit" variant="primary" size="sm" disabled={busy || !name.trim()}>
              Create
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setCreating(false)
                setError(null)
              }}
              disabled={busy}
            >
              Cancel
            </Button>
          </form>
        )}
      </div>
      {error && <div className="project-bar__error">{error}</div>}
    </div>
  )
}
