import { useId, useState } from 'react'
import { api } from '../../api/client'
import type { DevTask, TaskArea } from '../../api/types'
import { Badge } from '../ui/Badge'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import { TECH_AREA_LABEL } from '../../lib/techAreas'

const TASK_AREA_LABEL: Record<TaskArea, string> = {
  frontend: 'Frontend',
  backend: 'Backend',
  data: 'Data',
  integration: 'Integration',
  infrastructure: 'Infrastructure',
  testing: 'Testing',
}

interface Props {
  projectId: string
  task: DevTask
  /** The parent writes prompts (one at a time, also in batches), so it owns that state. */
  writing: boolean
  /** Why the parent's last attempt to write this task's prompt failed, if it did. */
  writeError: string | null
  disabled: boolean
  onWrite: (task: DevTask) => void
  onChanged: (task: DevTask) => void
  onDeleted: (taskId: string) => void
}

/** One technical task (a Jira Sub-task) and its coding prompt. */
export function DevTaskRow({ projectId, task, writing, writeError, disabled, onWrite, onChanged, onDeleted }: Props) {
  const editorId = useId()
  const saved = task.edited_prompt ?? task.coding_prompt ?? ''
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(saved)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // A regenerated prompt replaces the text being shown.
  const [shownFor, setShownFor] = useState(saved)
  if (shownFor !== saved) {
    setShownFor(saved)
    setText(saved)
  }

  const dirty = text !== saved
  const hasPrompt = task.coding_prompt !== null
  const edited = task.edited_prompt !== null

  async function run(action: () => Promise<void>, fallback: string) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback)
    } finally {
      setBusy(false)
    }
  }

  function regenerate() {
    if ((edited || dirty) && !window.confirm('Writing the prompt again replaces it, including your edits. Continue?')) return
    setOpen(true)
    onWrite(task)
  }

  function remove() {
    if (!window.confirm(`Delete the task “${task.title}”? This cannot be undone.`)) return
    run(async () => {
      await api.deleteDevTask(projectId, task.id)
      onDeleted(task.id)
    }, 'Could not delete the task')
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setError('Could not copy automatically — select the text and copy it manually.')
    }
  }

  return (
    <li className="dev-task">
      <div className="dev-task__head">
        <Badge tone="neutral">{TASK_AREA_LABEL[task.area] ?? task.area}</Badge>
        <div className="dev-task__text">
          <p className="dev-task__title">{task.title}</p>
          <p className="dev-task__summary">{task.summary}</p>
        </div>
        <div className="dev-task__status">
          {!hasPrompt ? (
            <Badge>No prompt yet</Badge>
          ) : (
            <Badge tone="success" icon="check">
              {edited ? 'Prompt edited' : 'Prompt ready'}
            </Badge>
          )}
          {task.jira_key && (
            <a href={task.jira_url ?? undefined} target="_blank" rel="noreferrer" className="dev-task__jira">
              {task.jira_key} <Icon name="external" size={13} />
            </a>
          )}
          {task.tech_decision_needed && (
            <Badge tone="warning" icon="alert">
              Decision needed
              {task.decision_areas.length > 0 && `: ${task.decision_areas.map((a) => TECH_AREA_LABEL[a] ?? a).join(', ')}`}
            </Badge>
          )}
        </div>
      </div>

      <div className="dev-task__actions">
        {!hasPrompt ? (
          <Button variant="primary" size="sm" icon="sparkles" loading={writing} disabled={disabled || busy} onClick={() => onWrite(task)}>
            Write coding prompt
          </Button>
        ) : (
          <>
            <Button variant="secondary" size="sm" icon={open ? 'chevron-up' : 'eye'} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
              {open ? 'Hide prompt' : 'Show prompt'}
            </Button>
            <Button variant="ghost" size="sm" icon="refresh" loading={writing} disabled={disabled || busy} onClick={regenerate}>
              Write again
            </Button>
          </>
        )}
        <Button variant="ghost" size="sm" icon="trash" disabled={disabled || busy || writing} onClick={remove} aria-label={`Delete task ${task.title}`}>
          Delete
        </Button>
      </div>

      {writeError && !writing && <Banner tone="danger">{writeError}</Banner>}
      {error && <Banner tone="danger">{error}</Banner>}

      {open && hasPrompt && (
        <div className="dev-task__prompt">
          <label htmlFor={editorId} className="dev-task__prompt-label">
            Coding prompt{edited ? ' (edited)' : ''}
            {task.prompt_generated_at && (
              <span className="dev-task__prompt-date"> · written {new Date(task.prompt_generated_at).toLocaleString()}</span>
            )}
          </label>
          <textarea
            id={editorId}
            className="dev-task__editor"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={18}
            spellCheck={false}
            disabled={busy || writing}
          />
          <div className="dev-task__prompt-actions">
            <Button variant="primary" size="sm" icon="copy" onClick={copy}>
              {copied ? 'Copied' : 'Copy'}
            </Button>
            {dirty && (
              <Button
                variant="secondary"
                size="sm"
                loading={busy}
                onClick={() =>
                  run(async () => onChanged(await api.updateDevTask(projectId, task.id, { edited_prompt: text })), 'Could not save your edits')
                }
              >
                Save edits
              </Button>
            )}
            {edited && !dirty && (
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() =>
                  window.confirm('Go back to the generated prompt? Your edits are discarded.') &&
                  run(async () => onChanged(await api.updateDevTask(projectId, task.id, { edited_prompt: null })), 'Could not reset the prompt')
                }
              >
                Back to generated
              </Button>
            )}
          </div>
        </div>
      )}
    </li>
  )
}
