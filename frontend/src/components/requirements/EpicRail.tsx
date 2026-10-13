import type { ItemFields, RequirementItem } from '../../api/types'
import { storyStatus } from '../../lib/stories'
import { AddItemForm } from '../AddItemForm'
import './EpicRail.css'

interface EpicRailProps {
  projectId: string
  docId: string
  epics: RequirementItem[]
  stories: RequirementItem[]
  /** External ID of the selected epic, or null for every epic. */
  selected: string | null
  onSelect: (externalId: string | null) => void
  onCreateEpic: (text: string, fields?: ItemFields) => Promise<void>
}

export function EpicRail({ projectId, docId, epics, stories, selected, onSelect, onCreateEpic }: EpicRailProps) {
  return (
    <nav className="epic-rail" aria-label="Epics">
      <p className="epic-rail__heading">Epics</p>

      <button
        type="button"
        className={`epic-rail__item ${selected === null ? 'epic-rail__item--active' : ''}`}
        aria-current={selected === null ? 'true' : undefined}
        onClick={() => onSelect(null)}
      >
        <span className="epic-rail__id">All</span>
        <span className="epic-rail__name">Every story</span>
        <span className="epic-rail__count">{stories.length}</span>
      </button>

      {epics.map((epic) => {
        const own = stories.filter((s) => s.parent_id === epic.id)
        const needInput = own.filter((s) => storyStatus(s) === 'needs_input').length
        const active = selected === epic.external_id
        return (
          <button
            key={epic.id}
            type="button"
            className={`epic-rail__item ${active ? 'epic-rail__item--active' : ''}`}
            aria-current={active ? 'true' : undefined}
            onClick={() => onSelect(epic.external_id)}
          >
            <span className="epic-rail__id">{epic.external_id}</span>
            <span className="epic-rail__name">{epic.text}</span>
            <span className="epic-rail__count">{own.length}</span>
            {needInput > 0 && (
              <span className="epic-rail__alert" title={`${needInput} need input`}>
                <span className="sr-only">{needInput} need input</span>
                <span aria-hidden="true">{needInput}</span>
              </span>
            )}
          </button>
        )
      })}

      <div className="epic-rail__add">
        <AddItemForm
          kind="epic"
          triggerLabel="+ Add epic"
          projectId={projectId}
          docId={docId}
          onCreate={(text, fields) => onCreateEpic(text, fields)}
        />
      </div>
    </nav>
  )
}
