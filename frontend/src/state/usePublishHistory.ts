import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ConfluencePublishInfo, RequirementsDetail } from '../api/types'

export interface PublishEvent {
  version: number
  at: string
  url: string
}

const MAX_VERSIONS = 8

/**
 * Confluence publications across the chain of versions. PDF downloads aren't
 * logged anywhere (they're generated on demand), so the history only lists
 * what the system actually recorded.
 */
export function usePublishHistory(projectId: string, current: RequirementsDetail | null | undefined) {
  const [events, setEvents] = useState<PublishEvent[]>([])
  const [loading, setLoading] = useState(true)
  const docId = current?.document.id
  const published = current?.document.type_metadata?.confluence as ConfluencePublishInfo | undefined
  const publishedAt = published?.published_at

  useEffect(() => {
    if (!current) {
      setEvents([])
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)

    async function walk() {
      const found: PublishEvent[] = []
      let detail: RequirementsDetail | null = current ?? null
      for (let i = 0; i < MAX_VERSIONS && detail; i += 1) {
        const info = detail.document.type_metadata?.confluence as ConfluencePublishInfo | undefined
        if (info) found.push({ version: detail.document.version, at: info.published_at, url: info.page_url })
        const previousId: string | null = detail.document.previous_version_id
        detail = previousId ? await api.getRequirementsVersion(projectId, previousId).catch(() => null) : null
      }
      if (!cancelled) {
        setEvents(found.sort((a, b) => b.at.localeCompare(a.at)))
        setLoading(false)
      }
    }
    walk()
    return () => {
      cancelled = true
    }
    // The chain only changes when the current version or its publication does.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, docId, publishedAt])

  return { events, loading }
}
