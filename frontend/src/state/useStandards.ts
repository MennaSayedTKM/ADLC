import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { StandingPolicy } from '../api/types'

/** Company standards (the API calls them standing policies), active ones first. */
export function useStandards() {
  const [standards, setStandards] = useState<StandingPolicy[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .listPolicies()
      .then((list) => !cancelled && setStandards(list))
      .catch(() => undefined) // an unreachable list just means no chips; the page still works
      .finally(() => !cancelled && setLoaded(true))
    return () => {
      cancelled = true
    }
  }, [])

  return { standards, active: standards.filter((s) => s.is_active), loaded }
}
