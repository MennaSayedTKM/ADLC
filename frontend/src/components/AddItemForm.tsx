import { useState } from 'react'
import { api } from '../api/client'
import type { AcceptanceCriterion, EpicDraft, ItemFields, StoryDraft } from '../api/types'
import { Button } from './ui/Button'
import './AddItemForm.css'

interface AddItemFormProps {
  kind: 'epic' | 'story'
  onCreate: (text: string, fields?: ItemFields) => Promise<void>
  triggerLabel: string
  triggerClassName?: string
  projectId: string
  docId: string
  parentId?: string // the epic a story is being drafted under (AI-assisted mode only)
}

type Mode = 'manual' | 'ai'

export function AddItemForm({
  kind,
  onCreate,
  triggerLabel,
  triggerClassName = '',
  projectId,
  docId,
  parentId,
}: AddItemFormProps) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('manual')
  const [text, setText] = useState('')
  const [acText, setAcText] = useState('')
  const [subject, setSubject] = useState('')
  const [draftFields, setDraftFields] = useState<ItemFields | null>(null)
  // The raw last response, kept only so Regenerate can hand it back as
  // context ("give me something different from this") — draftFields above
  // is the edited/working copy the PM sees and can tweak before adding.
  const [lastDraft, setLastDraft] = useState<EpicDraft | StoryDraft | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function reset() {
    setText('')
    setAcText('')
    setSubject('')
    setDraftFields(null)
    setLastDraft(null)
    setMode('manual')
    setError(null)
    setOpen(false)
  }

  async function handleCreateManual(e: React.FormEvent) {
    e.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    setError(null)
    try {
      const criteria: AcceptanceCriterion[] | undefined =
        kind === 'story'
          ? acText
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean)
              .map((line) => ({ text: line, out_of_scope: false }))
          : undefined
      await onCreate(text.trim(), criteria ? { acceptance_criteria: criteria } : undefined)
      reset()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create')
    } finally {
      setBusy(false)
    }
  }

  async function handleGenerate(regenerate = false) {
    if (!subject.trim()) return
    setBusy(true)
    setError(null)
    try {
      const draft = await api.generateItemDraft(projectId, docId, {
        kind,
        subject: subject.trim(),
        parent_id: parentId,
        previous_draft: regenerate && lastDraft ? lastDraft : undefined,
      })
      if (kind === 'epic' && 'assumptions' in draft) {
        setLastDraft(draft)
        setDraftFields({ assumptions: draft.assumptions, dependencies: draft.dependencies })
        setText(draft.title)
      } else if (kind === 'story' && 'description' in draft) {
        setLastDraft(draft)
        setDraftFields({
          description: draft.description,
          scenarios: draft.scenarios,
          acceptance_criteria: draft.acceptance_criteria,
          error_handling: draft.error_handling,
        })
        setText(draft.title)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not generate a draft')
    } finally {
      setBusy(false)
    }
  }

  async function handleConfirmDraft() {
    if (!text.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onCreate(text.trim(), { ...draftFields, origin: 'pm_ai_assisted' })
      reset()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button type="button" className={`add-item-trigger ${triggerClassName}`} onClick={() => setOpen(true)}>
        {triggerLabel}
      </button>
    )
  }

  return (
    <div className="add-item-form">
      <div className="add-item-form__mode-toggle" role="tablist">
        <button
          type="button"
          role="tab"
          className={`add-item-form__mode-btn ${mode === 'manual' ? 'add-item-form__mode-btn--active' : ''}`}
          onClick={() => {
            setMode('manual')
            setDraftFields(null)
            setText('')
          }}
          disabled={busy}
        >
          Add manually
        </button>
        <button
          type="button"
          role="tab"
          className={`add-item-form__mode-btn ${mode === 'ai' ? 'add-item-form__mode-btn--active' : ''}`}
          onClick={() => {
            setMode('ai')
            setText('')
          }}
          disabled={busy}
        >
          ✨ Add with AI
        </button>
      </div>

      {mode === 'manual' && (
        <form onSubmit={handleCreateManual}>
          <input
            className="add-item-form__input"
            autoFocus
            placeholder={kind === 'epic' ? 'Epic title' : 'Story text'}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={busy}
          />
          {kind === 'story' && (
            <textarea
              className="add-item-form__textarea"
              placeholder="Acceptance criteria, one per line (optional)"
              value={acText}
              onChange={(e) => setAcText(e.target.value)}
              rows={2}
              disabled={busy}
            />
          )}
          {error && <div className="add-item-form__error">{error}</div>}
          <div className="add-item-form__actions">
            <Button type="submit" variant="primary" size="sm" disabled={busy || !text.trim()}>
              {busy ? 'Adding…' : `Add ${kind}`}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={reset} disabled={busy}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {mode === 'ai' && !draftFields && (
        <div>
          <textarea
            className="add-item-form__textarea"
            autoFocus
            placeholder={`Describe the ${kind === 'epic' ? 'epic' : 'story'} you want — the AI will draft the rest.`}
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            rows={3}
            disabled={busy}
          />
          {error && <div className="add-item-form__error">{error}</div>}
          <div className="add-item-form__actions">
            <Button type="button" variant="primary" size="sm" onClick={() => handleGenerate(false)} disabled={busy || !subject.trim()}>
              {busy ? 'Generating…' : 'Generate'}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={reset} disabled={busy}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {mode === 'ai' && draftFields && (
        <div className="add-item-form__draft-preview">
          <div className="add-item-form__draft-badge">AI-drafted — review before adding</div>
          <label className="add-item-form__field-label">Title</label>
          <input className="add-item-form__input" value={text} onChange={(e) => setText(e.target.value)} disabled={busy} />
          {draftFields.description !== undefined && (
            <>
              <label className="add-item-form__field-label">Description</label>
              <textarea
                className="add-item-form__textarea"
                rows={2}
                value={draftFields.description}
                onChange={(e) => setDraftFields((f) => (f ? { ...f, description: e.target.value } : f))}
                disabled={busy}
              />
            </>
          )}
          {draftFields.scenarios !== undefined && (
            <p className="add-item-form__draft-summary">
              {draftFields.scenarios.length} scenario{draftFields.scenarios.length === 1 ? '' : 's'},{' '}
              {draftFields.acceptance_criteria?.length ?? 0} acceptance criteri
              {draftFields.acceptance_criteria?.length === 1 ? 'on' : 'a'} — editable after adding.
            </p>
          )}
          {draftFields.dependencies !== undefined && draftFields.dependencies.length > 0 && (
            <p className="add-item-form__draft-summary">Dependencies: {draftFields.dependencies.join('; ')}</p>
          )}
          {error && <div className="add-item-form__error">{error}</div>}
          <div className="add-item-form__actions">
            <Button type="button" variant="primary" size="sm" onClick={handleConfirmDraft} disabled={busy || !text.trim()}>
              {busy ? 'Adding…' : `Add ${kind}`}
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={() => handleGenerate(true)} disabled={busy}>
              {busy ? 'Regenerating…' : 'Regenerate'}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={reset} disabled={busy}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
