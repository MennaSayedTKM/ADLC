import { useEffect, useRef, useState } from 'react'
import { useOptionalProject } from '../../state/ProjectContext'
import { SEARCH_SHORTCUT } from '../../lib/platform'
import { useTheme } from '../../lib/theme'
import { HOME_HREF, projectHref, type ProjectPage, type Route } from '../../lib/router'
import { ComingSoon } from '../ui/ComingSoon'
import { Icon } from '../ui/Icon'
import { useShell } from './ShellContext'
import './Topbar.css'

const PAGE_TITLE: Record<ProjectPage, string> = {
  overview: 'Overview',
  sources: 'Sources',
  requirements: 'Requirements',
  design: 'Design',
  validate: 'Validate design',
  publish: 'Publish & export',
  'dev-stories': 'Dev stories',
}

function useResolvedDark(preference: 'system' | 'light' | 'dark'): boolean {
  const [systemDark, setSystemDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return preference === 'system' ? systemDark : preference === 'dark'
}

function Breadcrumbs({ route }: { route: Route }) {
  const project = useOptionalProject()

  if (route.name === 'project' && project) {
    return (
      <nav className="crumbs" aria-label="Breadcrumb">
        <a href={projectHref(project.project.id)} className="crumbs__link">
          {project.project.name}
        </a>
        <span className="crumbs__sep" aria-hidden="true">
          /
        </span>
        <span className="crumbs__current" aria-current="page">
          {PAGE_TITLE[route.page]}
        </span>
      </nav>
    )
  }

  const title = route.name === 'standards' ? 'Company standards' : route.name === 'settings' ? 'Settings' : 'Projects'
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {route.name !== 'home' && (
        <>
          <a href={HOME_HREF} className="crumbs__link">
            Projects
          </a>
          <span className="crumbs__sep" aria-hidden="true">
            /
          </span>
        </>
      )}
      <span className="crumbs__current" aria-current="page">
        {title}
      </span>
    </nav>
  )
}

function NotificationsButton() {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="popover-anchor" ref={rootRef}>
      <button
        type="button"
        className="icon-button"
        aria-label="Notifications"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="bell" size={19} />
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Notifications">
          <p className="popover__title">
            Notifications <ComingSoon />
          </p>
          <p className="popover__text">
            Soon you&rsquo;ll be told here when a generation finishes or a version needs approval. For now, progress
            appears on the page where you started the work.
          </p>
        </div>
      )}
    </div>
  )
}

export function Topbar({ route }: { route: Route }) {
  const { setActionsNode, setNavOpen, setPaletteOpen } = useShell()
  const { preference, setPreference } = useTheme()
  const dark = useResolvedDark(preference)
  const project = useOptionalProject()

  return (
    <header className="topbar">
      <button type="button" className="icon-button topbar__menu" aria-label="Open navigation" onClick={() => setNavOpen(true)}>
        <Icon name="menu" size={20} />
      </button>

      <Breadcrumbs route={route} />

      <div className="topbar__actions" ref={setActionsNode} />

      <button type="button" className="search-trigger" onClick={() => setPaletteOpen(true)}>
        <Icon name="search" size={17} />
        <span className="search-trigger__label">{project ? 'Search project' : 'Search'}</span>
        <kbd className="search-trigger__kbd">{SEARCH_SHORTCUT}</kbd>
      </button>

      <NotificationsButton />

      <button
        type="button"
        className="icon-button"
        aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
        title={dark ? 'Switch to light theme' : 'Switch to dark theme'}
        onClick={() => setPreference(dark ? 'light' : 'dark')}
      >
        <Icon name={dark ? 'sun' : 'moon'} size={19} />
      </button>

      <button
        type="button"
        className="icon-button"
        aria-label="Invite teammates (coming soon)"
        title="Invite teammates — coming soon"
        disabled
      >
        <Icon name="user-plus" size={19} />
      </button>
    </header>
  )
}
