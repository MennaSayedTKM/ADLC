import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { JiraPreviewData } from '../api/types'

/**
 * The project's Jira connection and what sending each planned epic would do.
 * A project that isn't connected yet connects to the company default key (if
 * Settings has one) once, on first load: a read-only check of the Jira project.
 * If that fails, connectError says why and the person can enter another key.
 */
export function useJiraPreview(projectId: string) {
  const [preview, setPreview] = useState<JiraPreviewData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connectError, setConnectError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const triedDefault = useRef<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      let data = await api.getJiraPreview(projectId)
      const defaultKey = data.default_project_key
      if (!data.settings && defaultKey && triedDefault.current !== `${projectId}:${defaultKey}`) {
        triedDefault.current = `${projectId}:${defaultKey}`
        try {
          data = await api.connectJiraProject(projectId, defaultKey)
          setConnectError(null)
        } catch (err) {
          setConnectError(
            `The company default Jira project ${defaultKey} couldn’t be connected: ${err instanceof Error ? err.message : 'unknown error'}`,
          )
        }
      }
      setPreview(data)
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

  return { preview, error, connectError, loading, refresh, setPreview }
}
