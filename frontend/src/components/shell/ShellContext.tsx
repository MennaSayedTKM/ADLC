import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

interface ShellState {
  actionsNode: HTMLElement | null
  setActionsNode: (node: HTMLElement | null) => void
  navOpen: boolean
  setNavOpen: (open: boolean) => void
  paletteOpen: boolean
  setPaletteOpen: (open: boolean) => void
}

const ShellContext = createContext<ShellState | null>(null)

export function ShellProvider({ children }: { children: ReactNode }) {
  const [actionsNode, setActionsNode] = useState<HTMLElement | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)

  const value = useMemo(
    () => ({ actionsNode, setActionsNode, navOpen, setNavOpen, paletteOpen, setPaletteOpen }),
    [actionsNode, navOpen, paletteOpen],
  )
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
}

export function useShell(): ShellState {
  const ctx = useContext(ShellContext)
  if (!ctx) throw new Error('useShell must be used inside <ShellProvider>')
  return ctx
}

/**
 * Renders its children into the top bar, so each page can put its primary
 * actions (Approve, Export …) where they stay visible while the page scrolls.
 */
export function TopbarActions({ children }: { children: ReactNode }) {
  const { actionsNode } = useShell()
  return actionsNode ? createPortal(children, actionsNode) : null
}
