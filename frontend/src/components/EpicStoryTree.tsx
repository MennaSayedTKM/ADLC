import { useState } from 'react'
import type { ItemFields, RequirementItem } from '../api/types'
import { AddItemForm } from './AddItemForm'
import { ProvenanceBadge } from './ProvenanceBadge'
import { StoryRow } from './StoryRow'
import { Button } from './ui/Button'
import { TrashIcon } from './ui/TrashIcon'
import './EpicStoryTree.css'

interface EpicStoryTreeProps {
  projectId: string
  docId: string
  epics: RequirementItem[]
  stories: RequirementItem[]
  onSaveItem: (itemId: string, fields: ItemFields) => Promise<void>
  onCreateEpic: (text: string, fields?: ItemFields) => Promise<void>
  onCreateStory: (parentId: string, fields: ItemFields & { text: string }) => Promise<void>
  onDeleteItem: (itemId: string) => Promise<void>
}

export function EpicStoryTree({
  projectId,
  docId,
  epics,
  stories,
  onSaveItem,
  onCreateEpic,
  onCreateStory,
  onDeleteItem,
}: EpicStoryTreeProps) {
  // Collapsed by default (lazy initializer runs once, against whatever
  // epics are already loaded by the time this mounts) so a PM sees every
  // epic title at a glance first, rather than every story from every epic
  // all at once. A newly-added epic isn't in this initial set, so it opens
  // expanded — the PM just created it and wants to see it immediately.
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set(epics.map((e) => e.id)))

  const [deletingEpicId, setDeletingEpicId] = useState<string | null>(null)

  function toggle(epicId: string) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(epicId)) next.delete(epicId)
      else next.add(epicId)
      return next
    })
  }

  async function handleDeleteEpic(epic: RequirementItem, storyCount: number) {
    const warning =
      storyCount > 0
        ? `Delete epic "${epic.text}" and all ${storyCount} stor${storyCount === 1 ? 'y' : 'ies'} under it? This can't be undone.`
        : `Delete epic "${epic.text}"? This can't be undone.`
    if (!window.confirm(warning)) return
    setDeletingEpicId(epic.id)
    try {
      await onDeleteItem(epic.id)
    } finally {
      setDeletingEpicId(null)
    }
  }

  return (
    <div className="epic-tree">
      {epics.length === 0 && (
        <div className="epic-tree--empty">No epics extracted from this document yet.</div>
      )}

      {epics.length > 0 && (
        <div className="epic-tree__toolbar">
          <button type="button" className="epic-tree__toolbar-btn" onClick={() => setCollapsed(new Set())}>
            Expand all
          </button>
          <button
            type="button"
            className="epic-tree__toolbar-btn"
            onClick={() => setCollapsed(new Set(epics.map((e) => e.id)))}
          >
            Collapse all
          </button>
        </div>
      )}

      {epics.map((epic) => {
        const epicStories = stories.filter((s) => s.parent_id === epic.id)
        const isCollapsed = collapsed.has(epic.id)
        return (
          <section key={epic.id} className="epic-group">
            <div
              className="epic-group__header"
              role="button"
              tabIndex={0}
              onClick={() => toggle(epic.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  toggle(epic.id)
                }
              }}
              aria-expanded={!isCollapsed}
            >
              <span className={`epic-group__chevron ${isCollapsed ? 'epic-group__chevron--collapsed' : ''}`}>
                ▾
              </span>
              <span className="epic-group__id">{epic.external_id}</span>
              {epic.source_reference && (
                <span className="epic-group__source-ref" title="Source reference">
                  {epic.source_reference}
                </span>
              )}
              <EpicTitle epic={epic} onSaveItem={onSaveItem} />
              <ProvenanceBadge origin={epic.origin} />
              <span className="epic-group__count">
                {epicStories.length} stor{epicStories.length === 1 ? 'y' : 'ies'}
              </span>
              <button
                type="button"
                className="epic-group__delete-btn"
                title="Delete epic"
                onClick={(e) => {
                  e.stopPropagation()
                  handleDeleteEpic(epic, epicStories.length)
                }}
                disabled={deletingEpicId === epic.id}
              >
                {deletingEpicId === epic.id ? '…' : <TrashIcon />}
              </button>
            </div>
            {!isCollapsed && <EpicMeta epic={epic} onSaveItem={onSaveItem} />}
            {!isCollapsed && (
              <ul className="epic-group__stories">
                {epicStories.map((story) => (
                  <StoryRow
                    key={story.id}
                    story={story}
                    onSave={onSaveItem}
                    onDelete={onDeleteItem}
                    projectId={projectId}
                    docId={docId}
                  />
                ))}
                {epicStories.length === 0 && (
                  <li className="epic-group__no-stories">No stories under this epic.</li>
                )}
                <li className="epic-group__add-story">
                  <AddItemForm
                    kind="story"
                    triggerLabel="+ Add story"
                    projectId={projectId}
                    docId={docId}
                    parentId={epic.id}
                    onCreate={(text, fields) => onCreateStory(epic.id, { text, ...fields })}
                  />
                </li>
              </ul>
            )}
          </section>
        )
      })}

      <AddItemForm
        kind="epic"
        triggerLabel="+ Add epic"
        triggerClassName="epic-tree__add-epic-trigger"
        projectId={projectId}
        docId={docId}
        onCreate={(text, fields) => onCreateEpic(text, fields)}
      />
    </div>
  )
}

function EpicTitle({
  epic,
  onSaveItem,
}: {
  epic: RequirementItem
  onSaveItem: (itemId: string, fields: ItemFields) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(epic.text)
  const [busy, setBusy] = useState(false)

  if (editing) {
    return (
      <input
        className="epic-group__title-input"
        value={text}
        autoFocus
        disabled={busy}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => setText(e.target.value)}
        onBlur={async () => {
          setBusy(true)
          try {
            if (text.trim() && text.trim() !== epic.text) {
              await onSaveItem(epic.id, { text: text.trim() })
            }
          } finally {
            setBusy(false)
            setEditing(false)
          }
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
          if (e.key === 'Escape') {
            setText(epic.text)
            setEditing(false)
          }
        }}
      />
    )
  }

  return (
    <span
      className="epic-group__title"
      onClick={(e) => {
        e.stopPropagation()
        setEditing(true)
      }}
      title="Click to rename this epic"
    >
      {epic.text}
    </span>
  )
}

function StringListEditor({
  items,
  onChange,
  placeholder,
}: {
  items: string[]
  onChange: (items: string[]) => void
  placeholder: string
}) {
  return (
    <div className="epic-group__meta-editor-list">
      {items.map((item, i) => (
        <div key={i} className="epic-group__meta-edit-row">
          <input
            className="epic-group__meta-input"
            value={item}
            placeholder={placeholder}
            onChange={(e) => onChange(items.map((it, j) => (j === i ? e.target.value : it)))}
          />
          <button
            type="button"
            className="epic-group__meta-remove-btn"
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            aria-label="Remove"
          >
            ×
          </button>
        </div>
      ))}
      <button type="button" className="epic-group__meta-add-btn" onClick={() => onChange([...items, ''])}>
        + Add
      </button>
    </div>
  )
}

function EpicMeta({
  epic,
  onSaveItem,
}: {
  epic: RequirementItem
  onSaveItem: (itemId: string, fields: ItemFields) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [assumptions, setAssumptions] = useState<string[]>(epic.assumptions ?? [])
  const [dependencies, setDependencies] = useState<string[]>(epic.dependencies ?? [])
  const [sourceReference, setSourceReference] = useState(epic.source_reference ?? '')

  const hasContent =
    (epic.assumptions?.length ?? 0) > 0 || (epic.dependencies?.length ?? 0) > 0 || !!epic.source_reference

  function startEdit(e: React.MouseEvent) {
    e.stopPropagation()
    setAssumptions(epic.assumptions ?? [])
    setDependencies(epic.dependencies ?? [])
    setSourceReference(epic.source_reference ?? '')
    setError(null)
    setEditing(true)
  }

  async function handleSave() {
    setBusy(true)
    setError(null)
    try {
      await onSaveItem(epic.id, {
        assumptions: assumptions.filter((a) => a.trim()),
        dependencies: dependencies.filter((d) => d.trim()),
        source_reference: sourceReference.trim(),
      })
      setEditing(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <div className="epic-group__meta epic-group__meta--editing" onClick={(e) => e.stopPropagation()}>
        <div className="epic-group__meta-block">
          <span className="epic-group__meta-heading">Source reference</span>
          <input
            className="epic-group__meta-input"
            value={sourceReference}
            placeholder="e.g. 4.1.A"
            onChange={(e) => setSourceReference(e.target.value)}
          />
        </div>
        <div className="epic-group__meta-block">
          <span className="epic-group__meta-heading">Assumptions</span>
          <StringListEditor items={assumptions} onChange={setAssumptions} placeholder="Assumption" />
        </div>
        <div className="epic-group__meta-block">
          <span className="epic-group__meta-heading">Dependencies</span>
          <StringListEditor items={dependencies} onChange={setDependencies} placeholder="Dependency" />
        </div>
        {error && <div className="epic-group__meta-error">{error}</div>}
        <div className="epic-group__meta-actions">
          <Button variant="primary" size="sm" onClick={handleSave} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setEditing(false)} disabled={busy}>
            Cancel
          </Button>
        </div>
      </div>
    )
  }

  if (!hasContent) {
    return (
      <div className="epic-group__meta epic-group__meta--empty" onClick={startEdit}>
        + Add source reference / assumptions / dependencies
      </div>
    )
  }

  return (
    <div className="epic-group__meta" onClick={startEdit} title="Click to edit">
      {epic.source_reference && (
        <div className="epic-group__meta-block">
          <span className="epic-group__meta-heading">Source reference</span>
          <span>{epic.source_reference}</span>
        </div>
      )}
      {epic.assumptions && epic.assumptions.length > 0 && (
        <div className="epic-group__meta-block">
          <span className="epic-group__meta-heading">Assumptions</span>
          <ul>
            {epic.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
      {epic.dependencies && epic.dependencies.length > 0 && (
        <div className="epic-group__meta-block">
          <span className="epic-group__meta-heading">Dependencies</span>
          <ul>
            {epic.dependencies.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
