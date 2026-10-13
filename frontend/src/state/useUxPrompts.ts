import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { UxPrompt, UxPromptSources } from '../api/types'

/** Loads the approved version's prompt sources and the prompts generated so far. */
export function useUxPrompts(projectId: string) {
  const [sources, setSources] = useState<UxPromptSources | null>(null)
  const [prompts, setPrompts] = useState<UxPrompt[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshSources = useCallback(
    () => api.getUxPromptSources(projectId).then(setSources).catch(() => undefined),
    [projectId],
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setSources(null)
    setPrompts([])
    Promise.all([api.getUxPromptSources(projectId), api.listUxPrompts(projectId)])
      .then(([src, list]) => {
        if (cancelled) return
        setSources(src)
        setPrompts(list)
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load design prompts'))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [projectId])

  // The blueprint is created or regenerated in place; features are always new rows.
  const onBlueprint = useCallback(
    (prompt: UxPrompt) => {
      setPrompts((prev) => (prev.some((p) => p.id === prompt.id) ? prev.map((p) => (p.id === prompt.id ? prompt : p)) : [prompt, ...prev]))
      refreshSources()
    },
    [refreshSources],
  )

  const onFeature = useCallback((prompt: UxPrompt) => setPrompts((prev) => [...prev, prompt]), [])

  const onChanged = useCallback(
    (updated: UxPrompt) => {
      setPrompts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
      if (updated.mode === 'foundation' || updated.screens.length > 0) refreshSources()
    },
    [refreshSources],
  )

  const onDeleted = useCallback(
    (id: string) => {
      setPrompts((prev) => prev.filter((p) => p.id !== id))
      refreshSources()
    },
    [refreshSources],
  )

  return { sources, prompts, error, loading, refreshSources, onBlueprint, onFeature, onChanged, onDeleted }
}
