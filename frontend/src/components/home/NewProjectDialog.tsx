import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import { plural } from '../../lib/format'
import { navigate, projectHref } from '../../lib/router'
import { guessResourceKind, KIND_LABEL } from '../../lib/sources'
import { useApp } from '../../state/AppContext'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import { Modal } from '../ui/Modal'
import './NewProjectDialog.css'

interface NewProjectDialogProps {
  open: boolean
  onClose: () => void
  /** Files chosen on the home page ("Start from any document"); added as the project's first sources. */
  initialFiles?: File[]
}

function nameFromFile(file: File | undefined): string {
  if (!file) return ''
  return file.name
    .replace(/\.[^.]+$/, '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+v?\d+(\.\d+)*$/i, '')
    .trim()
}

export function NewProjectDialog({ open, onClose, initialFiles = [] }: NewProjectDialogProps) {
  const { createProject } = useApp()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [failedUploads, setFailedUploads] = useState<string[]>([])
  const [createdId, setCreatedId] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setName(nameFromFile(initialFiles[0]))
    setError(null)
    setFailedUploads([])
    setCreatedId(null)
    // Reset only when the dialog opens; the file list is stable for that session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    setError(null)
    try {
      const project = await createProject(trimmed)
      const failed: string[] = []
      for (const file of initialFiles) {
        try {
          await api.uploadIntakeResource(project.id, file, guessResourceKind(file.name))
        } catch {
          failed.push(file.name)
        }
      }
      if (failed.length > 0) {
        // Keep the dialog open so the person sees which files didn't make it.
        setFailedUploads(failed)
        setCreatedId(project.id)
        return
      }
      onClose()
      navigate(projectHref(project.id, 'sources'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the project')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New project"
      description="Give it a name — you can add documents next."
    >
      <form className="new-project" onSubmit={handleSubmit}>
        <label className="new-project__field">
          <span className="new-project__label">Project name</span>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Customer Onboarding Portal"
            disabled={busy || createdId !== null}
            maxLength={120}
          />
        </label>

        {initialFiles.length > 0 && (
          <div className="new-project__files">
            <p className="new-project__label">{plural(initialFiles.length, 'document')} will be added as sources</p>
            <ul>
              {initialFiles.map((file) => (
                <li key={file.name + file.size} className="new-project__file">
                  <Icon name={/\.(png|jpe?g|webp|bmp|tiff?)$/i.test(file.name) ? 'image' : 'file'} size={16} />
                  <span className="new-project__file-name">{file.name}</span>
                  <span className="new-project__file-kind">{KIND_LABEL[guessResourceKind(file.name)]}</span>
                </li>
              ))}
            </ul>
            <p className="new-project__hint">We guess each type from its name. You can check them on the next screen.</p>
          </div>
        )}

        {error && <Banner tone="danger">{error}</Banner>}
        {failedUploads.length > 0 && (
          <Banner tone="warning">
            The project was created, but {failedUploads.join(', ')} couldn&rsquo;t be added. You can add{' '}
            {failedUploads.length === 1 ? 'it' : 'them'} again on the Sources page.
          </Banner>
        )}

        <div className="new-project__actions">
          {createdId ? (
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                onClose()
                navigate(projectHref(createdId, 'sources'))
              }}
            >
              Continue to sources
            </Button>
          ) : (
            <>
              <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" loading={busy} disabled={!name.trim()}>
                Create project
              </Button>
            </>
          )}
        </div>
      </form>
    </Modal>
  )
}
