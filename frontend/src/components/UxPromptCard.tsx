import { useState } from 'react'
import { api } from '../api/client'
import type { UxPrompt, UxPromptMode } from '../api/types'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { Banner } from './ui/Banner'
import './UxPromptCard.css'

const MODE_LABEL: Record<UxPromptMode, string> = {
  foundation: 'New platform',
  new_feature: 'New feature',
  edit_existing: 'Edit existing',
}

interface Props {
  projectId: string
  prompt: UxPrompt
  onChanged: (prompt: UxPrompt) => void
  onDeleted: (promptId: string) => void
}

export function UxPromptCard({ projectId, prompt, onChanged, onDeleted }: Props) {
  const saved = prompt.edited_text ?? prompt.prompt_text
  const [text, setText] = useState(saved)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty = text !== saved
  const overLimit = text.length > prompt.soft_char_limit
  const hasEdits = prompt.edited_text !== null

  async function run<T>(action: () => Promise<T>, fallback: string): Promise<T | undefined> {
    setBusy(true)
    setError(null)
    try {
      return await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback)
      return undefined
    } finally {
      setBusy(false)
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setError('Could not copy automatically — select the text and copy it manually.')
    }
  }

  async function handleSave() {
    const updated = await run(() => api.updateUxPrompt(projectId, prompt.id, text), 'Could not save your edits')
    if (updated) {
      onChanged(updated)
      setText(updated.edited_text ?? updated.prompt_text)
    }
  }

  async function handleReset() {
    const updated = await run(() => api.updateUxPrompt(projectId, prompt.id, null), 'Could not reset the prompt')
    if (updated) {
      onChanged(updated)
      setText(updated.prompt_text)
    }
  }

  async function handleRegenerate() {
    if ((hasEdits || dirty) && !window.confirm('Regenerating replaces the text, including your edits. Continue?')) {
      return
    }
    const updated = await run(() => api.regenerateUxPrompt(projectId, prompt.id), 'Could not regenerate the prompt')
    if (updated) {
      onChanged(updated)
      setText(updated.prompt_text)
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete the ${prompt.epic_external_id} prompt? This cannot be undone.`)) return
    const done = await run(async () => {
      await api.deleteUxPrompt(projectId, prompt.id)
      return true
    }, 'Could not delete the prompt')
    if (done) onDeleted(prompt.id)
  }

  return (
    <article className="ux-card">
      <header className="ux-card__header">
        <div className="ux-card__title">
          <span className="ux-card__epic-id">{prompt.epic_external_id}</span>
          {prompt.epic_title}
        </div>
        <div className="ux-card__badges">
          <Badge tone="accent">{MODE_LABEL[prompt.mode]}</Badge>
          {hasEdits && <Badge>Edited</Badge>}
          {prompt.is_stale && <Badge tone="warning">Outdated</Badge>}
        </div>
      </header>

      <p className="ux-card__meta">
        Stories: {prompt.story_external_ids.join(', ')} · generated{' '}
        {new Date(prompt.created_at).toLocaleString()}
      </p>

      {prompt.is_stale && (
        <Banner tone="warning">
          A newer requirements version replaced the one this was generated from. Review the stories
          and regenerate if they changed.
        </Banner>
      )}

      <textarea
        className="ux-card__text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={14}
        spellCheck={false}
        aria-label={`Figma Make prompt for ${prompt.epic_external_id}`}
        disabled={busy}
      />

      <div className="ux-card__footer">
        <span className={`ux-card__count ${overLimit ? 'ux-card__count--over' : ''}`}>
          {text.length.toLocaleString()} characters
          {overLimit && ` · over the ~${prompt.soft_char_limit.toLocaleString()} target, may use more Figma credits`}
        </span>
        <div className="ux-card__actions">
          {dirty && (
            <>
              <Button size="sm" variant="secondary" onClick={handleSave} disabled={busy}>
                Save edits
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setText(saved)} disabled={busy}>
                Discard changes
              </Button>
            </>
          )}
          {!dirty && hasEdits && (
            <Button size="sm" variant="ghost" onClick={handleReset} disabled={busy}>
              Reset to generated
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={handleRegenerate} disabled={busy}>
            {busy ? 'Working…' : 'Regenerate'}
          </Button>
          <Button size="sm" variant="ghost" onClick={handleDelete} disabled={busy}>
            Delete
          </Button>
          <Button size="sm" variant="primary" onClick={handleCopy} disabled={busy}>
            {copied ? 'Copied' : 'Copy prompt'}
          </Button>
        </div>
      </div>

      {error && <Banner tone="danger">{error}</Banner>}
    </article>
  )
}
