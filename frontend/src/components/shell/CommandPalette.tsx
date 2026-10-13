import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useApp } from '../../state/AppContext'
import { useOptionalProject } from '../../state/ProjectContext'
import { HOME_HREF, SETTINGS_HREF, STANDARDS_HREF, navigate, projectHref } from '../../lib/router'
import { Icon, type IconName } from '../ui/Icon'
import { useShell } from './ShellContext'
import './CommandPalette.css'

interface PaletteItem {
  id: string
  group: string
  title: string
  subtitle?: string
  href: string
  icon: IconName
}

const GROUP_ORDER = ['Pages', 'Stories', 'Epics', 'Gaps', 'Projects']
const MAX_PER_GROUP = 6

function score(item: PaletteItem, query: string): number {
  const title = item.title.toLowerCase()
  const subtitle = (item.subtitle ?? '').toLowerCase()
  if (title.startsWith(query)) return 3
  if (title.includes(query)) return 2
  if (subtitle.includes(query)) return 1
  return 0
}

/** ⌘K / Ctrl+K — jump to any page, project, story, epic or gap without hunting through tabs. */
export function CommandPalette() {
  const { paletteOpen, setPaletteOpen } = useShell()
  const { projects } = useApp()
  const project = useOptionalProject()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen(!paletteOpen)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [paletteOpen, setPaletteOpen])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (paletteOpen && !dialog.open) {
      setQuery('')
      setActive(0)
      dialog.showModal()
      inputRef.current?.focus()
    }
    if (!paletteOpen && dialog.open) dialog.close()
  }, [paletteOpen])

  const items = useMemo<PaletteItem[]>(() => {
    const list: PaletteItem[] = []
    if (project) {
      const id = project.project.id
      list.push(
        { id: 'p-overview', group: 'Pages', title: 'Overview', href: projectHref(id, 'overview'), icon: 'home' },
        { id: 'p-sources', group: 'Pages', title: 'Sources', href: projectHref(id, 'sources'), icon: 'upload' },
        { id: 'p-req', group: 'Pages', title: 'Requirements', href: projectHref(id, 'requirements'), icon: 'list' },
        { id: 'p-design', group: 'Pages', title: 'Design prompts', href: projectHref(id, 'design'), icon: 'layout' },
        { id: 'p-validate', group: 'Pages', title: 'Validate design', href: projectHref(id, 'validate'), icon: 'target' },
        { id: 'p-publish', group: 'Pages', title: 'Publish & export', href: projectHref(id, 'publish'), icon: 'send' },
      )
      const reqs = project.requirements
      if (reqs) {
        const epicTitle = new Map(reqs.epics.map((e) => [e.id, `${e.external_id} · ${e.text}`]))
        for (const story of reqs.stories) {
          list.push({
            id: `s-${story.id}`,
            group: 'Stories',
            title: story.text,
            subtitle: `${story.external_id} · ${epicTitle.get(story.parent_id ?? '') ?? ''}`,
            href: projectHref(id, 'requirements', { story: story.external_id }),
            icon: 'file',
          })
        }
        for (const epic of reqs.epics) {
          list.push({
            id: `e-${epic.id}`,
            group: 'Epics',
            title: epic.text,
            subtitle: epic.external_id,
            href: projectHref(id, 'requirements', { epic: epic.external_id }),
            icon: 'layout',
          })
        }
        for (const gap of reqs.gaps.filter((g) => g.status === 'open')) {
          list.push({
            id: `g-${gap.id}`,
            group: 'Gaps',
            title: gap.description,
            subtitle: gap.location ?? (gap.page !== null ? `p.${gap.page}` : undefined),
            href: projectHref(id, 'requirements', { tab: 'gaps' }),
            icon: 'alert',
          })
        }
      }
    }
    list.push(
      { id: 'n-home', group: 'Pages', title: 'All projects', href: HOME_HREF, icon: 'home' },
      { id: 'n-standards', group: 'Pages', title: 'Company standards', href: STANDARDS_HREF, icon: 'shield' },
      { id: 'n-settings', group: 'Pages', title: 'Settings', href: SETTINGS_HREF, icon: 'settings' },
    )
    for (const p of projects) {
      list.push({ id: `proj-${p.id}`, group: 'Projects', title: p.name, href: projectHref(p.id), icon: 'folder' })
    }
    return list
  }, [project, projects])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    const matched = q
      ? items
          .map((item) => ({ item, s: score(item, q) }))
          .filter((m) => m.s > 0)
          .sort((a, b) => b.s - a.s)
          .map((m) => m.item)
      : items
    const perGroup = new Map<string, number>()
    const limited = matched.filter((item) => {
      const used = perGroup.get(item.group) ?? 0
      perGroup.set(item.group, used + 1)
      return used < MAX_PER_GROUP
    })
    return limited.sort((a, b) => GROUP_ORDER.indexOf(a.group) - GROUP_ORDER.indexOf(b.group))
  }, [items, query])

  useEffect(() => setActive(0), [query])

  function go(item: PaletteItem | undefined) {
    if (!item) return
    setPaletteOpen(false)
    navigate(item.href)
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      go(results[active])
    }
  }

  useEffect(() => {
    document.getElementById(`palette-option-${active}`)?.scrollIntoView({ block: 'nearest' })
  }, [active])

  let lastGroup = ''

  return (
    <dialog
      ref={dialogRef}
      className="palette"
      aria-label="Search"
      onClose={() => setPaletteOpen(false)}
      onClick={(e) => {
        if (e.target === e.currentTarget) setPaletteOpen(false)
      }}
    >
      <div className="palette__search">
        <Icon name="search" size={18} />
        <input
          ref={inputRef}
          className="palette__input"
          placeholder={project ? 'Search stories, gaps, pages…' : 'Search projects and pages…'}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={results[active] ? `palette-option-${active}` : undefined}
          aria-label="Search"
        />
        <kbd className="palette__kbd">Esc</kbd>
      </div>

      <ul id="palette-list" className="palette__list" role="listbox">
        {results.length === 0 && <li className="palette__empty">Nothing matches “{query}”.</li>}
        {results.map((item, index) => {
          const showGroup = item.group !== lastGroup
          lastGroup = item.group
          return (
            <li key={item.id} role="presentation">
              {showGroup && <p className="palette__group">{item.group}</p>}
              <div
                id={`palette-option-${index}`}
                role="option"
                aria-selected={index === active}
                className={`palette__option ${index === active ? 'palette__option--active' : ''}`}
                onMouseMove={() => setActive(index)}
                onClick={() => go(item)}
              >
                <Icon name={item.icon} size={17} />
                <span className="palette__title">{item.title}</span>
                {item.subtitle && <span className="palette__subtitle">{item.subtitle}</span>}
              </div>
            </li>
          )
        })}
      </ul>
    </dialog>
  )
}
