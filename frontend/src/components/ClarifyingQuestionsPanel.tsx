import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ClarifyingQuestion } from '../api/types'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import './ClarifyingQuestionsPanel.css'

interface ClarifyingQuestionsPanelProps {
  projectId: string
}

function buildCopyText(questions: ClarifyingQuestion[]): string {
  return questions
    .map((q, i) => {
      const lines = [`${i + 1}. ${q.question_text}`]
      if (q.status === 'answered' && q.answer_text) lines.push(`   Answer: ${q.answer_text}`)
      return lines.join('\n')
    })
    .join('\n\n')
}

export function ClarifyingQuestionsPanel({ projectId }: ClarifyingQuestionsPanelProps) {
  const [questions, setQuestions] = useState<ClarifyingQuestion[] | undefined>(undefined)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    try {
      setQuestions(await api.listClarifyingQuestions(projectId))
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load clarifying questions')
    }
  }, [projectId])

  useEffect(() => {
    load()
  }, [load])

  async function handleGenerate() {
    setGenerating(true)
    setGenerateError(null)
    try {
      await api.generateClarifyingQuestions(projectId)
      await load()
    } catch (err) {
      setGenerateError(
        err instanceof ApiError && err.status === 422
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not generate clarifying questions',
      )
    } finally {
      setGenerating(false)
    }
  }

  async function handleCopyAll() {
    if (!questions || questions.length === 0) return
    try {
      await navigator.clipboard.writeText(buildCopyText(questions))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setGenerateError("Couldn't copy to the clipboard — your browser may be blocking clipboard access.")
    }
  }

  async function updateQuestion(questionId: string, status: 'answered' | 'skipped', answerText?: string) {
    const updated = await api.updateClarifyingQuestion(projectId, questionId, { status, answer_text: answerText })
    setQuestions((prev) => prev?.map((q) => (q.id === questionId ? updated : q)))
  }

  return (
    <div className="clarifying-questions-panel">
      <div className="clarifying-questions-panel__header">
        <h2 className="clarifying-questions-panel__title">Clarifying questions</h2>
        <span className="clarifying-questions-panel__count">{questions?.length ?? 0}</span>
      </div>
      <p className="clarifying-questions-panel__hint">
        Generate plain-language questions to relay to the client — filling real gaps here before
        extraction makes for higher-quality epics and stories. This is optional and never blocks
        running extraction.
      </p>

      {loadError && <div className="clarifying-questions-panel__error">{loadError}</div>}

      <div className="clarifying-questions-panel__actions">
        <Button type="button" variant="secondary" size="sm" onClick={handleGenerate} disabled={generating}>
          {generating ? 'Generating…' : 'Generate clarifying questions'}
        </Button>
        {questions && questions.length > 0 && (
          <Button type="button" variant="ghost" size="sm" onClick={handleCopyAll}>
            {copied ? 'Copied!' : 'Copy all as plain text'}
          </Button>
        )}
      </div>

      {generateError && <div className="clarifying-questions-panel__error">{generateError}</div>}

      {questions && questions.length > 0 && (
        <ul className="clarifying-questions-panel__list">
          {questions.map((q) => (
            <QuestionCard key={q.id} question={q} onUpdate={updateQuestion} />
          ))}
        </ul>
      )}
    </div>
  )
}

function QuestionCard({
  question,
  onUpdate,
}: {
  question: ClarifyingQuestion
  onUpdate: (questionId: string, status: 'answered' | 'skipped', answerText?: string) => Promise<void>
}) {
  const [answer, setAnswer] = useState(question.answer_text ?? '')
  const [busy, setBusy] = useState<'answer' | 'skip' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const statusTone = question.status === 'answered' ? 'success' : question.status === 'skipped' ? 'neutral' : 'accent'

  async function run(kind: 'answer' | 'skip') {
    setBusy(kind)
    setError(null)
    try {
      await onUpdate(question.id, kind === 'answer' ? 'answered' : 'skipped', kind === 'answer' ? answer : undefined)
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not save`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <li className="cq-card">
      <div className="cq-card__top">
        {question.topic_area && <Badge tone="accent">{question.topic_area}</Badge>}
        <Badge tone={statusTone}>{question.status}</Badge>
      </div>
      <p className="cq-card__question">{question.question_text}</p>
      {question.why_it_matters && <p className="cq-card__why">{question.why_it_matters}</p>}
      <textarea
        className="cq-card__answer-input"
        placeholder="Record the client's answer here…"
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        disabled={busy !== null}
        rows={2}
      />
      {error && <div className="cq-card__error">{error}</div>}
      <div className="cq-card__actions">
        <Button variant="secondary" size="sm" onClick={() => run('answer')} disabled={busy !== null || !answer.trim()}>
          {busy === 'answer' ? 'Saving…' : 'Save answer'}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => run('skip')} disabled={busy !== null}>
          {busy === 'skip' ? 'Skipping…' : 'Skip'}
        </Button>
      </div>
    </li>
  )
}
