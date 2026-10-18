import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DevOverview, DevStory, DevTask } from '../api/types'

/** The Dev stories page's data: the overview, plus helpers that put a changed story or task back in place. */
export function useDevStories(projectId: string) {
  const [overview, setOverview] = useState<DevOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(
    () =>
      api
        .getDevOverview(projectId)
        .then((data) => {
          setOverview(data)
          setError(null)
        })
        .catch((err) => setError(err instanceof Error ? err.message : 'Could not load development stories')),
    [projectId],
  )

  useEffect(() => {
    setLoading(true)
    refresh().finally(() => setLoading(false))
  }, [refresh])

  const replaceEpicStories = useCallback((epicExternalId: string, stories: DevStory[]) => {
    setOverview((prev) =>
      prev && {
        ...prev,
        epics: prev.epics.map((e) => (e.external_id === epicExternalId ? { ...e, dev_stories: stories } : e)),
      },
    )
  }, [])

  const replaceStory = useCallback((story: DevStory) => {
    setOverview((prev) =>
      prev && {
        ...prev,
        epics: prev.epics.map((e) => ({
          ...e,
          dev_stories: e.dev_stories.map((s) => (s.id === story.id ? story : s)),
        })),
      },
    )
  }, [])

  const replaceTask = useCallback((task: DevTask) => {
    setOverview((prev) =>
      prev && {
        ...prev,
        epics: prev.epics.map((e) => ({
          ...e,
          dev_stories: e.dev_stories.map((s) => ({
            ...s,
            tasks: s.tasks.map((t) => (t.id === task.id ? task : t)),
          })),
        })),
      },
    )
  }, [])

  return { overview, error, loading, refresh, replaceEpicStories, replaceStory, replaceTask }
}
