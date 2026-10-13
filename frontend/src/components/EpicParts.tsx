import { useState } from 'react'
import type { ItemFields, RequirementItem } from '../api/types'
import { Button } from './ui/Button'
import './EpicParts.css'

type SaveItem = (itemId: string, fields: ItemFields) => Promise<void>

/** Click-to-rename epic title. */
export function EpicTitle({ epic, onSaveItem }: { epic: RequirementItem; onSaveItem: SaveItem }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(epic.text)
  const [busy, setBusy] = useState(false)

  if (editing) {
    return (
      <input
        className="epic-title-input"
        value={text}
        autoFocus
        disabled={busy}
        aria-label="Epic name"
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
    <button type="button" className="epic-title" onClick={() => setEditing(true)} title="Click to rename this epic">
      {epic.text}
    </button>
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
    <div className="epic-meta__list">
      {items.map((item, i) => (
        <div key={i} className="epic-meta__row">
          <input
            value={item}
            placeholder={placeholder}
            aria-label={placeholder}
            onChange={(e) => onChange(items.map((it, j) => (j === i ? e.target.value : it)))}
          />
          <button
            type="button"
            className="epic-meta__remove"
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            aria-label={`Remove ${placeholder.toLowerCase()}`}
          >
            ×
          </button>
        </div>
      ))}
      <button type="button" className="link-button epic-meta__add" onClick={() => onChange([...items, ''])}>
        + Add
      </button>
    </div>
  )
}

/** An epic's source reference, assumptions and dependencies — read view that edits in place. */
export function EpicMeta({ epic, onSaveItem }: { epic: RequirementItem; onSaveItem: SaveItem }) {
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [assumptions, setAssumptions] = useState<string[]>(epic.assumptions ?? [])
  const [dependencies, setDependencies] = useState<string[]>(epic.dependencies ?? [])
  const [sourceReference, setSourceReference] = useState(epic.source_reference ?? '')

  const hasContent =
    (epic.assumptions?.length ?? 0) > 0 || (epic.dependencies?.length ?? 0) > 0 || !!epic.source_reference

  function startEdit() {
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
      <div className="epic-meta epic-meta--editing">
        <label className="epic-meta__block">
          <span className="epic-meta__heading">Source reference</span>
          <input value={sourceReference} placeholder="e.g. 4.1.A" onChange={(e) => setSourceReference(e.target.value)} />
        </label>
        <div className="epic-meta__block">
          <span className="epic-meta__heading">Assumptions</span>
          <StringListEditor items={assumptions} onChange={setAssumptions} placeholder="Assumption" />
        </div>
        <div className="epic-meta__block">
          <span className="epic-meta__heading">Dependencies</span>
          <StringListEditor items={dependencies} onChange={setDependencies} placeholder="Dependency" />
        </div>
        {error && <p className="epic-meta__error">{error}</p>}
        <div className="epic-meta__actions">
          <Button variant="primary" size="sm" onClick={handleSave} loading={busy}>
            Save
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
      <button type="button" className="epic-meta epic-meta--empty" onClick={startEdit}>
        + Add source reference, assumptions or dependencies
      </button>
    )
  }

  return (
    <div className="epic-meta">
      <div className="epic-meta__read">
        {epic.source_reference && (
          <div className="epic-meta__block">
            <span className="epic-meta__heading">Source reference</span>
            <span>{epic.source_reference}</span>
          </div>
        )}
        {epic.assumptions && epic.assumptions.length > 0 && (
          <div className="epic-meta__block">
            <span className="epic-meta__heading">Assumptions</span>
            <ul>
              {epic.assumptions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        )}
        {epic.dependencies && epic.dependencies.length > 0 && (
          <div className="epic-meta__block">
            <span className="epic-meta__heading">Dependencies</span>
            <ul>
              {epic.dependencies.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <button type="button" className="link-button" onClick={startEdit}>
        Edit
      </button>
    </div>
  )
}
