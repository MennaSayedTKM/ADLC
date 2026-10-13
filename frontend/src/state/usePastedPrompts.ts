import { useCallback, useState } from 'react'

/**
 * Which prompts the person has already pasted into Figma Make. Nothing is sent
 * to Figma from here, so this is a personal checklist kept in this browser.
 */
export function usePastedPrompts(projectId: string) {
  const key = `tkmind:pasted:${projectId}`

  const [pasted, setPasted] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(key) ?? '[]') as string[])
    } catch {
      return new Set()
    }
  })

  const toggle = useCallback(
    (promptId: string) => {
      setPasted((prev) => {
        const next = new Set(prev)
        if (next.has(promptId)) next.delete(promptId)
        else next.add(promptId)
        try {
          localStorage.setItem(key, JSON.stringify([...next]))
        } catch {
          // storage blocked — the tick still works for this session
        }
        return next
      })
    },
    [key],
  )

  const markPasted = useCallback(
    (promptId: string) => {
      setPasted((prev) => {
        if (prev.has(promptId)) return prev
        const next = new Set(prev).add(promptId)
        try {
          localStorage.setItem(key, JSON.stringify([...next]))
        } catch {
          // see above
        }
        return next
      })
    },
    [key],
  )

  return { pasted, toggle, markPasted }
}
