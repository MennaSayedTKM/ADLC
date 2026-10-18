import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { JiraPreviewData } from '../api/types'

/** The project's Jira connection and what sending each planned epic would do. Reads nothing from Jira. */
export function useJiraPreview(projectId: string) {
  const [preview, setPreview] = useState<JiraPreviewData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setPreview(await api.getJiraPreview(projectId))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the Jira preview')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { preview, error, loading, refresh, setPreview }
}
