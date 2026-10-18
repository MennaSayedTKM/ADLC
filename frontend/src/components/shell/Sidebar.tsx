import { useEffect, useRef, useState } from 'react'
import { useApp } from '../../state/AppContext'
import { useOptionalProject } from '../../state/ProjectContext'
import { initials } from '../../lib/format'
import { summarizeAlignment } from '../../lib/design'
import { isApproved } from '../../lib/lifecycle'
import { HOME_HREF, SETTINGS_HREF, STANDARDS_HREF, projectHref, type ProjectPage, type Route } from '../../lib/router'
import { Badge } from '../ui/Badge'
import { ButtonLink } from '../ui/Button'
import { ComingSoon } from '../ui/ComingSoon'
import { Icon, type IconName } from '../ui/Icon'
import './Sidebar.css'

interface NavItem {
  key: string
  label: string
  icon: IconName
  href: string
  active: boolean
  trailing?: React.ReactNode
  soon?: boolean
}

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate: () => void }) {
  return (
    <a
      href={item.href}
      className={`nav-link ${item.active ? 'nav-link--active' : ''}`}
      aria-current={item.active ? 'page' : undefined}
      onClick={onNavigate}
    >
      <Icon name={item.icon} size={18} />
      <span className="nav-link__label">{item.label}</span>
      {item.soon ? <ComingSoon /> : item.trailing}
    </a>
  )
}

function ProjectSwitcher({ onNavigate }: { onNavigate: () => void }) {
  const { projects } = useApp()
  const project = useOptionalProject()
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

  if (!project) return null

  return (
    <div className="switcher" ref={rootRef}>
      <button
        type="button"
        className="switcher__button"
        aria-expanded={open}
        aria-controls="project-switcher-menu"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="switcher__avatar" aria-hidden="true">
          {initials(project.project.name)}
        </span>
        <span className="switcher__text">
          <span className="switcher__eyebrow">Project</span>
          <span className="switcher__name">{project.project.name}</span>
        </span>
        <Icon name="chevron-down" size={16} />
      </button>

      {open && (
        <ul className="switcher__menu" id="project-switcher-menu" aria-label="Switch project">
          {projects.map((p) => (
            <li key={p.id}>
              <a
                href={projectHref(p.id)}
                className="switcher__option"
                aria-current={p.id === project.project.id ? 'true' : undefined}
                onClick={() => {
                  setOpen(false)
                  onNavigate()
                }}
              >
                <span className="switcher__avatar switcher__avatar--sm" aria-hidden="true">
                  {initials(p.name)}
                </span>
                <span className="switcher__option-name">{p.name}</span>
                {p.id === project.project.id && <Icon name="check" size={16} />}
              </a>
            </li>
          ))}
          <li className="switcher__footer">
            <a href={HOME_HREF} className="switcher__option" onClick={() => { setOpen(false); onNavigate() }}>
              <Icon name="home" size={16} />
              <span className="switcher__option-name">All projects</span>
            </a>
          </li>
        </ul>
      )}
    </div>
  )
}

export function Sidebar({ route, onNavigate, open }: { route: Route; onNavigate: () => void; open: boolean }) {
  const project = useOptionalProject()
  const inProject = route.name === 'project' && project
  const page: ProjectPage | null = route.name === 'project' ? route.page : null

  const workspace: NavItem[] = [
    { key: 'standards', label: 'Company standards', icon: 'shield', href: STANDARDS_HREF, active: route.name === 'standards' },
    { key: 'settings', label: 'Settings', icon: 'settings', href: SETTINGS_HREF, active: route.name === 'settings' },
  ]

  let build: NavItem[] = []
  let share: NavItem[] = []
  let overview: NavItem | null = null

  if (inProject && project) {
    const id = project.project.id
    const reqs = project.requirements
    const approved = isApproved(reqs ?? null)
    const gaps = reqs?.unresolved_gap_count ?? 0
    const designStep = project.steps.find((s) => s.id === 'design')
    const lock = !approved ? <Icon name="lock" size={14} label="Locked until requirements are approved" /> : null

    overview = { key: 'overview', label: 'Overview', icon: 'home', href: projectHref(id, 'overview'), active: page === 'overview' }

    build = [
      {
        key: 'sources',
        label: 'Sources',
        icon: 'upload',
        href: projectHref(id, 'sources'),
        active: page === 'sources',
        trailing: (project.resources?.length ?? 0) > 0 ? <span className="nav-count">{project.resources?.length}</span> : null,
      },
      {
        key: 'requirements',
        label: 'Requirements',
        icon: 'list',
        href: projectHref(id, 'requirements'),
        active: page === 'requirements',
        trailing: reqs ? (
          gaps > 0 && !approved ? (
            <Badge tone="warning" icon="alert">
              {gaps} {gaps === 1 ? 'gap' : 'gaps'}
            </Badge>
          ) : (
            <span className="nav-meta">v{reqs.document.version}</span>
          )
        ) : null,
      },
      {
        key: 'design',
        label: 'Design',
        icon: 'layout',
        href: projectHref(id, 'design'),
        active: page === 'design',
        trailing: designStep?.state === 'done' ? <Icon name="check" size={16} className="nav-done" label="Done" /> : lock,
      },
      {
        key: 'validate',
        label: 'Validate design',
        icon: 'target',
        href: projectHref(id, 'validate'),
        active: page === 'validate',
        trailing: project.design ? (
          <span className="nav-meta">{summarizeAlignment(project.design.reports).percent}%</span>
        ) : (
          lock
        ),
      },
      // Planned from the approved stories, then sent to Jira from Publish & export, so it comes first.
      { key: 'dev', label: 'Dev stories', icon: 'branch', href: projectHref(id, 'dev-stories'), active: page === 'dev-stories' },
    ]

    share = [
      { key: 'publish', label: 'Publish & export', icon: 'send', href: projectHref(id, 'publish'), active: page === 'publish' },
    ]
  }

  return (
    <aside className={`sidebar ${open ? 'sidebar--open' : ''}`} aria-label="Main navigation">
      <a href={HOME_HREF} className="sidebar__brand" onClick={onNavigate}>
        <span className="sidebar__mark" aria-hidden="true">
          TK
        </span>
        <span className="sidebar__wordmark">TKMiND</span>
      </a>

      <div className="sidebar__scroll">
        {inProject ? (
          <>
            <ProjectSwitcher onNavigate={onNavigate} />
            <nav className="nav">
              {overview && <NavLink item={overview} onNavigate={onNavigate} />}
              <p className="nav__group">Build</p>
              {build.map((item) => (
                <NavLink key={item.key} item={item} onNavigate={onNavigate} />
              ))}
              <p className="nav__group">Share</p>
              {share.map((item) => (
                <NavLink key={item.key} item={item} onNavigate={onNavigate} />
              ))}
              <p className="nav__group">Workspace</p>
              {workspace.map((item) => (
                <NavLink key={item.key} item={item} onNavigate={onNavigate} />
              ))}
            </nav>
          </>
        ) : (
          <nav className="nav">
            <NavLink
              item={{ key: 'projects', label: 'Projects', icon: 'home', href: HOME_HREF, active: route.name === 'home' }}
              onNavigate={onNavigate}
            />
            {workspace.map((item) => (
              <NavLink key={item.key} item={item} onNavigate={onNavigate} />
            ))}
          </nav>
        )}
      </div>

      {inProject && project?.ready && (
        <div className="guide" aria-live="polite">
          <p className="guide__title">
            <Icon name="sparkles" size={16} /> Not sure what&rsquo;s next?
          </p>
          <p className="guide__text">
            <strong>{project.next.title}.</strong> {project.next.body}
          </p>
          <ButtonLink
            variant="secondary"
            size="sm"
            href={projectHref(project.project.id, project.next.page, project.next.query)}
            iconAfter="arrow-right"
            onClick={onNavigate}
          >
            {project.next.label}
          </ButtonLink>
        </div>
      )}
    </aside>
  )
}
