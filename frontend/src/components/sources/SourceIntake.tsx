import { useRef, useState } from 'react'
import { api } from '../../api/client'
import type { IntakeResource, IntakeResourceKind } from '../../api/types'
import { relativeTime } from '../../lib/format'
import { guessResourceKind, KIND_LABEL, KIND_OPTIONS } from '../../lib/sources'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { ComingSoon } from '../ui/ComingSoon'
import { DropTarget } from '../ui/DropTarget'
import { Icon, type IconName } from '../ui/Icon'
import { Panel } from '../ui/Panel'
import './SourceIntake.css'

const FILE_TYPE_LABEL = { pdf: 'PDF', docx: 'Word', image: 'Image' } as const
const FILE_TYPE_ICON: Record<IntakeResource['file_type'], IconName> = { pdf: 'file', docx: 'file', image: 'image' }

interface SourceIntakeProps {
  projectId: string
  resources: IntakeResource[]
  setResources: (updater: (prev: IntakeResource[]) => IntakeResource[]) => void
  /** Sources can't change the generated requirements once a version exists. */
  locked: boolean
}

interface Uploading {
  key: string
  name: string
}

export function SourceIntake({ projectId, resources, setResources, locked }: SourceIntakeProps) {
  const [uploading, setUploading] = useState<Uploading[]>([])
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  // Files added in this session, so a type change can re-send them. The API has
  // no "change type" call, so Change = add again with the new type, then remove the old row.
  const retained = useRef(new Map<string, File>())

  async function addFiles(files: File[]) {
    setError(null)
    const failures: string[] = []
    for (const file of files) {
      const key = `${file.name}-${file.size}-${Date.now()}`
      setUploading((prev) => [...prev, { key, name: file.name }])
      try {
        const resource = await api.uploadIntakeResource(projectId, file, guessResourceKind(file.name), note.trim() || undefined)
        retained.current.set(resource.id, file)
        setResources((prev) => [...prev, resource])
      } catch (err) {
        failures.push(`${file.name}: ${err instanceof Error ? err.message : 'could not be added'}`)
      } finally {
        setUploading((prev) => prev.filter((u) => u.key !== key))
      }
    }
    if (failures.length > 0) setError(failures.join(' · '))
    else setNote('')
  }

  async function remove(resource: IntakeResource) {
    const previous = resources
    setResources((prev) => prev.filter((r) => r.id !== resource.id))
    try {
      await api.deleteIntakeResource(projectId, resource.id)
      retained.current.delete(resource.id)
    } catch (err) {
      setResources(() => previous)
      setError(err instanceof Error ? err.message : 'Could not remove this source')
    }
  }

  async function changeKind(resource: IntakeResource, kind: IntakeResourceKind) {
    const file = retained.current.get(resource.id)
    if (!file || kind === resource.resource_kind) return
    setError(null)
    try {
      const fresh = await api.uploadIntakeResource(projectId, file, kind, resource.notes ?? undefined)
      retained.current.set(fresh.id, file)
      await api.deleteIntakeResource(projectId, resource.id)
      retained.current.delete(resource.id)
      setResources((prev) => prev.map((r) => (r.id === resource.id ? fresh : r)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change the type')
    }
  }

  return (
    <>
      {!locked && (
        <DropTarget onFiles={addFiles} className="intake-drop">
          {({ open }) => (
            <div className="intake-drop__inner">
              <span className="intake-drop__icon" aria-hidden="true">
                <Icon name="upload" size={26} />
              </span>
              <p className="intake-drop__title">
                Drop files here, or{' '}
                <button type="button" className="intake-drop__browse" onClick={open}>
                  browse
                </button>
              </p>
              <p className="intake-drop__hint">PDF, Word, images · whiteboard photos work too</p>

              <div className="intake-drop__more">
                {(
                  [
                    ['link', 'Paste a link'],
                    ['file', 'Write a note'],
                    ['mic', 'Record a meeting'],
                  ] as const
                ).map(([icon, label]) => (
                  <Button key={label} variant="secondary" size="sm" icon={icon} disabled title="Coming soon — for now, add a file">
                    {label}
                    <ComingSoon />
                  </Button>
                ))}
              </div>

              <label className="intake-drop__note">
                <span className="sr-only">Note for the next file</span>
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Optional note for the next file — e.g. supplied by the client IT team"
                  maxLength={200}
                />
              </label>
            </div>
          )}
        </DropTarget>
      )}

      {error && <Banner tone="danger">{error}</Banner>}

      <Panel
        title={
          <>
            Your sources <span className="sources-count">· {resources.length}</span>
          </>
        }
        actions={<span className="sources-hint">We guess each type from the file name — correct it if we got it wrong</span>}
      >
        {resources.length === 0 && uploading.length === 0 ? (
          <p className="sources-empty">Nothing added yet. Your documents will appear here.</p>
        ) : (
          <ul className="source-list">
            {resources.map((r) => (
              <li key={r.id} className="source-row">
                <span className="source-row__icon" aria-hidden="true">
                  <Icon name={FILE_TYPE_ICON[r.file_type]} size={20} />
                </span>
                <div className="source-row__main">
                  <p className="source-row__name">{r.original_filename}</p>
                  <p className="source-row__meta">
                    {FILE_TYPE_LABEL[r.file_type]} · added {relativeTime(r.uploaded_at)}
                    {r.notes && <> · {r.notes}</>}
                  </p>
                  {r.processing_error && (
                    <p className="source-row__error">Couldn’t read this file: {r.processing_error}</p>
                  )}
                </div>

                {!locked && retained.current.has(r.id) ? (
                  <label className="kind-select" title="Changing the type re-reads the file">
                    <Icon name="sparkles" size={13} />
                    <span className="sr-only">Type of {r.original_filename}</span>
                    <select value={r.resource_kind} onChange={(e) => changeKind(r, e.target.value as IntakeResourceKind)}>
                      {KIND_OPTIONS.map((kind) => (
                        <option key={kind} value={kind}>
                          {KIND_LABEL[kind]}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <span className="kind-chip">{KIND_LABEL[r.resource_kind]}</span>
                )}

                {!locked && (
                  <button type="button" className="icon-action" onClick={() => remove(r)} aria-label={`Remove ${r.original_filename}`}>
                    <Icon name="x" size={17} />
                  </button>
                )}
              </li>
            ))}
            {uploading.map((u) => (
              <li key={u.key} className="source-row source-row--pending" aria-busy="true">
                <span className="source-row__icon" aria-hidden="true">
                  <span className="btn__spinner" />
                </span>
                <div className="source-row__main">
                  <p className="source-row__name">{u.name}</p>
                  <p className="source-row__meta">Reading the file…</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  )
}
