import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { IntakeResource, IntakeResourceKind } from '../api/types'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { TrashIcon } from './ui/TrashIcon'
import './ResourceStagingPanel.css'

const RESOURCE_KINDS: { value: IntakeResourceKind; label: string }[] = [
  { value: 'primary_requirements', label: 'Primary requirements' },
  { value: 'meeting_notes', label: 'Meeting notes' },
  { value: 'policy_reference', label: 'Client policy reference' },
  { value: 'other', label: 'Other' },
]

const KIND_LABEL: Record<IntakeResourceKind, string> = Object.fromEntries(
  RESOURCE_KINDS.map((k) => [k.value, k.label]),
) as Record<IntakeResourceKind, string>

const ACCEPT = '.pdf,.docx,.png,.jpg,.jpeg,.webp,.bmp,.tiff'

interface ResourceStagingPanelProps {
  projectId: string
}

export function ResourceStagingPanel({ projectId }: ResourceStagingPanelProps) {
  const [resources, setResources] = useState<IntakeResource[] | undefined>(undefined)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [resourceKind, setResourceKind] = useState<IntakeResourceKind>('primary_requirements')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      setResources(await api.listIntakeResources(projectId))
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load staged resources')
    }
  }, [projectId])

  useEffect(() => {
    load()
  }, [load])

  async function handleFile(file: File) {
    setBusy(true)
    setUploadError(null)
    try {
      const resource = await api.uploadIntakeResource(projectId, file, resourceKind, notes.trim() || undefined)
      setResources((prev) => [...(prev ?? []), resource])
      setNotes('')
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Could not stage this resource')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemove(resourceId: string) {
    const previous = resources
    setResources((prev) => prev?.filter((r) => r.id !== resourceId))
    try {
      await api.deleteIntakeResource(projectId, resourceId)
    } catch (err) {
      setResources(previous)
      setUploadError(err instanceof Error ? err.message : 'Could not remove this resource')
    }
  }

  return (
    <div className="resource-staging-panel">
      <div className="resource-staging-panel__header">
        <h2 className="resource-staging-panel__title">Staged resources</h2>
        <span className="resource-staging-panel__count">{resources?.length ?? 0}</span>
      </div>
      <p className="resource-staging-panel__hint">
        Add every resource that's relevant before running extraction — requirements docs, meeting
        notes, or a client's own policy references. PDF, Word, and images (e.g. a whiteboard
        photo) are all supported.
      </p>

      {loadError && <div className="resource-staging-panel__error">{loadError}</div>}

      {resources && resources.length > 0 && (
        <ul className="resource-staging-panel__list">
          {resources.map((r) => (
            <li key={r.id} className="resource-card">
              <div className="resource-card__top">
                <Badge tone="accent">{KIND_LABEL[r.resource_kind]}</Badge>
                <span className="resource-card__filename">{r.original_filename}</span>
                <button
                  type="button"
                  className="resource-card__remove"
                  onClick={() => handleRemove(r.id)}
                  aria-label={`Remove ${r.original_filename}`}
                >
                  <TrashIcon />
                </button>
              </div>
              {r.notes && <p className="resource-card__notes">{r.notes}</p>}
              {r.processing_error ? (
                <p className="resource-card__processing-error">
                  Couldn't process this file: {r.processing_error}
                </p>
              ) : (
                <p className="resource-card__preview">{r.extracted_text}</p>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="resource-staging-panel__add">
        <select
          className="resource-staging-panel__select"
          value={resourceKind}
          onChange={(e) => setResourceKind(e.target.value as IntakeResourceKind)}
          disabled={busy}
        >
          {RESOURCE_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        <input
          className="resource-staging-panel__notes-input"
          placeholder="Optional note (e.g. who supplied this)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={busy}
        />
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
        >
          {busy ? 'Adding…' : 'Add resource'}
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) handleFile(file)
            e.target.value = ''
          }}
        />
      </div>

      {uploadError && <div className="resource-staging-panel__error">{uploadError}</div>}
    </div>
  )
}
