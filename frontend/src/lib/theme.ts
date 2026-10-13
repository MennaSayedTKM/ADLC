import { useCallback, useEffect, useState } from 'react'

export type ThemePreference = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'tkmind:theme'

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // storage can be blocked (private mode) — fall through to following the OS
  }
  return 'system'
}

/** `system` removes the attribute so the prefers-color-scheme rule in index.css applies. */
export function applyTheme(preference: ThemePreference) {
  const root = document.documentElement
  if (preference === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', preference)
}

/** Called once before first paint so there is no flash of the wrong theme. */
export function initTheme() {
  applyTheme(readPreference())
}

export function useTheme() {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference)

  useEffect(() => {
    applyTheme(preference)
  }, [preference])

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // not persisted, still applied for this session
    }
  }, [])

  return { preference, setPreference }
}
