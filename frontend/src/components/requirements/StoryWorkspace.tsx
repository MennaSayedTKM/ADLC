import { useMemo, useState } from 'react'
import type { ItemFields, RequirementItem, RequirementsDetail } from '../../api/types'
import { plural } from '../../lib/format'
import { storyStatus, type StoryStatus } from '../../lib/stories'
import { AddItemForm } from '../AddItemForm'
import { EpicMeta, EpicTitle } from '../EpicParts'
import { ProvenanceBadge } from '../ProvenanceBadge'
import { StoryRow } from '../StoryRow'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import './StoryWorkspace.css'

type StatusFilter = 'all' | StoryStatus

interface StoryWorkspaceProps {
  projectId: string
  detail: RequirementsDetail
  selectedEpic: string | null
  /** A story to open and scroll to (from a ⌘K result or a link). */
  focusStory: string | null
  onSaveItem: (itemId: string, fields: ItemFields) => Promise<void>
  onCreateStory: (parentId: string, fields: ItemFields & { text: string }) => Promise<void>
  onDeleteItem: (itemId: string) => Promise<void>
}

export function StoryWorkspace({
  projectId,
  detail,
  selectedEpic,
  focusStory,
  onSaveItem,
  onCreateStory,
  onDeleteItem,
}: StoryWorkspaceProps) {
  const { epics, stories, document } = detail
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    // The first story opens by default so the page never loads as a wall of closed rows.
    const first = focusStory ?? stories[0]?.external_id
    return new Set(first ? [first] : [])
  })
  const [deletingEpic, setDeletingEpic] = useState(false)

  const epic = selectedEpic ? epics.find((e) => e.external_id === selectedEpic) ?? null : null

  const scoped = useMemo(() => (epic ? stories.filter((s) => s.parent_id === epic.id) : stories), [epic, stories])

  const counts = useMemo(
    () => ({
      all: scoped.length,
      ready: scoped.filter((s) => storyStatus(s) === 'ready').length,
      needs_input: scoped.filter((s) => storyStatus(s) === 'needs_input').length,
    }),
    [scoped],
  )

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return scoped.filter((s) => {
      if (status !== 'all' && storyStatus(s) !== status) return false
      if (!q) return true
      return (
        s.text.toLowerCase().includes(q) ||
        s.external_id.toLowerCase().includes(q) ||
        (s.description ?? '').toLowerCase().includes(q)
      )
    })
  }, [scoped, query, status])

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function sourceFor(story: RequirementItem): string | undefined {
    const parent = epics.find((e) => e.id === story.parent_id)
    const base = document.source_filename
    return parent?.source_reference ? `${base} · §${parent.source_reference}` : base
  }

  async function deleteEpic(target: RequirementItem) {
    const own = stories.filter((s) => s.parent_id === target.id).length
    const warning =
      own > 0
        ? `Delete epic “${target.text}” and all ${plural(own, 'story', 'stories')} under it? This can’t be undone.`
        : `Delete epic “${target.text}”? This can’t be undone.`
    if (!window.confirm(warning)) return
    setDeletingEpic(true)
    try {
      await onDeleteItem(target.id)
    } finally {
      setDeletingEpic(false)
    }
  }

  const groups = epic ? [{ epic, items: visible }] : epics.map((e) => ({ epic: e, items: visible.filter((s) => s.parent_id === e.id) }))

  return (
    <div className="story-workspace">
      <div className="story-toolbar">
        <label className="story-toolbar__search">
          <Icon name="search" size={16} />
          <span className="sr-only">Filter stories</span>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter stories by title or ID…" />
        </label>

        <div className="filter-chips" role="group" aria-label="Filter by status">
          {(
            [
              ['all', 'All'],
              ['ready', 'Ready'],
              ['needs_input', 'Needs input'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`filter-chip ${status === value ? 'filter-chip--active' : ''}`}
              aria-pressed={status === value}
              onClick={() => setStatus(value)}
            >
              {label} <span className="filter-chip__count">{counts[value]}</span>
            </button>
          ))}
        </div>

        <div className="story-toolbar__bulk">
          <button type="button" className="link-button" onClick={() => setExpanded(new Set(visible.map((s) => s.external_id)))}>
            Expand all
          </button>
          <button type="button" className="link-button" onClick={() => setExpanded(new Set())}>
            Collapse all
          </button>
        </div>
      </div>

      {epics.length === 0 && <p className="story-empty">No epics were found in this document yet. Add one to get started.</p>}

      {groups.map(({ epic: group, items }) => (
        <section key={group.id} className="story-group" aria-label={group.text}>
          <header className="story-group__header">
            <span className="story-group__id">{group.external_id}</span>
            <EpicTitle epic={group} onSaveItem={onSaveItem} />
            <ProvenanceBadge origin={group.origin} />
            <span className="story-group__count">{plural(stories.filter((s) => s.parent_id === group.id).length, 'story', 'stories')}</span>
            {epic && (
              <Button variant="ghost" size="sm" icon="trash" loading={deletingEpic} onClick={() => deleteEpic(group)}>
                Delete epic
              </Button>
            )}
          </header>

          {epic && <EpicMeta epic={group} onSaveItem={onSaveItem} />}

          <ul className="story-list">
            {items.map((story) => (
              <StoryRow
                key={story.id}
                story={story}
                projectId={projectId}
                docId={document.id}
                onSave={onSaveItem}
                onDelete={onDeleteItem}
                sourceLabel={sourceFor(story)}
                expanded={expanded.has(story.external_id)}
                onToggle={() => toggle(story.external_id)}
              />
            ))}
            {items.length === 0 && (
              <li className="story-empty">
                {query || status !== 'all' ? 'No stories match these filters.' : 'No stories under this epic yet.'}
              </li>
            )}
            <li>
              <AddItemForm
                kind="story"
                triggerLabel="+ Add story"
                projectId={projectId}
                docId={document.id}
                parentId={group.id}
                onCreate={(text, fields) => onCreateStory(group.id, { text, ...fields })}
              />
            </li>
          </ul>
        </section>
      ))}
    </div>
  )
}
