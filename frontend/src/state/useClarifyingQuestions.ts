import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ClarifyingQuestion } from '../api/types'

export function useClarifyingQuestions(projectId: string) {
  const [questions, setQuestions] = useState<ClarifyingQuestion[]>([])
  const [loaded, setLoaded] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .listClarifyingQuestions(projectId)
      .then((list) => !cancelled && setQuestions(list))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load questions'))
      .finally(() => !cancelled && setLoaded(true))
    return () => {
      cancelled = true
    }
  }, [projectId])

  const generate = useCallback(async () => {
    setGenerating(true)
    setError(null)
    try {
      await api.generateClarifyingQuestions(projectId)
      setQuestions(await api.listClarifyingQuestions(projectId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not suggest questions')
    } finally {
      setGenerating(false)
    }
  }, [projectId])

  const update = useCallback(
    async (questionId: string, status: 'answered' | 'skipped', answerText?: string) => {
      const updated = await api.updateClarifyingQuestion(projectId, questionId, { status, answer_text: answerText })
      setQuestions((prev) => prev.map((q) => (q.id === questionId ? updated : q)))
    },
    [projectId],
  )

  return { questions, loaded, generating, error, generate, update }
}
