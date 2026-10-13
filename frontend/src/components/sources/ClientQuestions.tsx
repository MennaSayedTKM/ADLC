import { useState } from 'react'
import type { ClarifyingQuestion } from '../../api/types'
import { plural } from '../../lib/format'
import { Badge } from '../ui/Badge'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Panel } from '../ui/Panel'
import './ClientQuestions.css'

interface ClientQuestionsProps {
  projectName: string
  questions: ClarifyingQuestion[]
  generating: boolean
  error: string | null
  hasSources: boolean
  readOnly?: boolean
  onGenerate: () => void
  onUpdate: (id: string, status: 'answered' | 'skipped', answer?: string) => Promise<void>
}

function emailBody(projectName: string, questions: ClarifyingQuestion[]): string {
  const lines = questions.map((q, i) => `${i + 1}. ${q.question_text}`)
  return [
    'Hi,',
    '',
    `While preparing the requirements for ${projectName} we have a few questions. Your answers will help us make the first draft much stronger:`,
    '',
    ...lines,
    '',
    'Thank you!',
  ].join('\n')
}

function QuestionRow({
  question,
  selected,
  onToggle,
  onUpdate,
  readOnly,
}: {
  question: ClarifyingQuestion
  selected: boolean
  onToggle: () => void
  onUpdate: ClientQuestionsProps['onUpdate']
  readOnly: boolean
}) {
  const [open, setOpen] = useState(false)
  const [answer, setAnswer] = useState(question.answer_text ?? '')
  const [busy, setBusy] = useState<'answer' | 'skip' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pending = question.status === 'pending'

  async function save(kind: 'answer' | 'skip') {
    setBusy(kind)
    setError(null)
    try {
      await onUpdate(question.id, kind === 'answer' ? 'answered' : 'skipped', kind === 'answer' ? answer : undefined)
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setBusy(null)
    }
  }

  return (
    <li className="cq-row">
      <div className="cq-row__main">
        <input
          type="checkbox"
          className="cq-row__check"
          checked={selected && pending}
          disabled={!pending}
          onChange={onToggle}
          aria-label={`Include in email: ${question.question_text}`}
        />
        <div className="cq-row__body">
          <p className={`cq-row__text ${pending ? '' : 'cq-row__text--done'}`}>{question.question_text}</p>
          <p className="cq-row__meta">
            {question.topic_area && <>Ask: {question.topic_area}</>}
            {question.why_it_matters && <span className="cq-row__why"> · {question.why_it_matters}</span>}
          </p>
          {question.status === 'answered' && question.answer_text && (
            <p className="cq-row__answer">
              <strong>Answer:</strong> {question.answer_text}
            </p>
          )}
        </div>
        <div className="cq-row__side">
          {question.status === 'answered' && <Badge tone="success" icon="check">Answered</Badge>}
          {question.status === 'skipped' && <Badge>Skipped</Badge>}
          {pending && !readOnly && (
            <button type="button" className="link-button" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
              {open ? 'Cancel' : 'Record answer'}
            </button>
          )}
        </div>
      </div>

      {open && (
        <div className="cq-row__form">
          <textarea
            rows={2}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Paste or type the client’s answer…"
            disabled={busy !== null}
            aria-label="Client’s answer"
          />
          {error && <p className="cq-row__error">{error}</p>}
          <div className="cq-row__actions">
            <Button size="sm" variant="primary" loading={busy === 'answer'} disabled={!answer.trim() || busy !== null} onClick={() => save('answer')}>
              Save answer
            </Button>
            <Button size="sm" variant="ghost" loading={busy === 'skip'} disabled={busy !== null} onClick={() => save('skip')}>
              Skip this question
            </Button>
          </div>
        </div>
      )}
    </li>
  )
}

export function ClientQuestions({ projectName, questions, generating, error, hasSources, readOnly = false, onGenerate, onUpdate }: ClientQuestionsProps) {
  const [deselected, setDeselected] = useState<Set<string>>(new Set())
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  const pending = questions.filter((q) => q.status === 'pending')
  const chosen = pending.filter((q) => !deselected.has(q.id))

  function toggle(id: string) {
    setDeselected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function copyEmail() {
    try {
      await navigator.clipboard.writeText(emailBody(projectName, chosen))
      setCopyError(false)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopyError(true)
    }
  }

  return (
    <Panel
      title={
        <span className="cq-title">
          Questions for the client <Badge>Optional</Badge>
        </span>
      }
      description={
        questions.length > 0
          ? `We spotted ${plural(pending.length, 'gap')} in your documents. Send these to the client now for a stronger first draft.`
          : hasSources
            ? 'Not sure what’s missing? We can read your sources and suggest what to ask the client.'
            : 'Add a source first, then we can suggest what to ask the client.'
      }
      actions={
        !readOnly && (
          <Button variant="secondary" icon="sparkles" loading={generating} disabled={!hasSources} onClick={onGenerate}>
            {questions.length > 0 ? 'Suggest more' : 'Suggest questions'}
          </Button>
        )
      }
    >
      {error && <Banner tone="danger">{error}</Banner>}

      {!collapsed && questions.length > 0 && (
        <>
          <ul className="cq-list">
            {questions.map((q) => (
              <QuestionRow key={q.id} question={q} selected={!deselected.has(q.id)} onToggle={() => toggle(q.id)} onUpdate={onUpdate} readOnly={readOnly} />
            ))}
          </ul>
          <div className="cq-footer">
            <Button variant="secondary" icon="copy" disabled={chosen.length === 0} onClick={copyEmail}>
              {copied ? 'Copied' : chosen.length > 0 ? `Copy ${plural(chosen.length, 'question')} as email` : 'Copy as email'}
            </Button>
            {pending.length > 0 && !readOnly && (
              <Button variant="ghost" onClick={() => setCollapsed(true)}>
                Skip for now
              </Button>
            )}
            {copyError && <span className="cq-row__error">Your browser blocked copying — select the questions and copy them by hand.</span>}
          </div>
        </>
      )}

      {collapsed && (
        <p className="cq-collapsed">
          Questions hidden. <button type="button" className="link-button" onClick={() => setCollapsed(false)}>Show them again</button>
        </p>
      )}
    </Panel>
  )
}
