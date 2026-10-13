import { useEffect, type ReactNode } from 'react'
import { useHash, type Route } from '../../lib/router'
import { CommandPalette } from './CommandPalette'
import { useShell } from './ShellContext'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import './Shell.css'

export function AppShell({ route, children }: { route: Route; children: ReactNode }) {
  const { navOpen, setNavOpen } = useShell()
  const hash = useHash()

  // A new page starts at the top, and the mobile drawer closes.
  useEffect(() => {
    window.scrollTo({ top: 0 })
    setNavOpen(false)
  }, [hash, setNavOpen])

  useEffect(() => {
    if (!navOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setNavOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navOpen, setNavOpen])

  return (
    <div className="shell">
      <a href="#main" className="skip-link" onClick={(e) => {
        e.preventDefault()
        document.getElementById('main')?.focus()
      }}>
        Skip to content
      </a>

      <Sidebar route={route} open={navOpen} onNavigate={() => setNavOpen(false)} />
      {navOpen && <div className="shell__scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />}

      <div className="shell__main">
        <Topbar route={route} />
        <main id="main" className="shell__content" tabIndex={-1}>
          {children}
        </main>
      </div>

      <CommandPalette />
    </div>
  )
}
