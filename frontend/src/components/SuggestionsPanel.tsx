import { useState } from 'react'
import type { RequirementItem } from '../api/types'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import './SuggestionsPanel.css'

interface SuggestionsPanelProps {
  suggestions: RequirementItem[] // pending ai_suggestion items, epic and story kinds mixed
  epics: RequirementItem[] // the real/visible epics, to label an existing parent
  onAccept: (itemId: string) => Promise<void>
  onDismiss: (itemId: string) => Promise<void>
}

export function SuggestionsPanel({ suggestions, epics, onAccept, onDismiss }: SuggestionsPanelProps) {
  const storySuggestions = suggestions.filter((s) => s.type === 'story')
  const epicSuggestions = suggestions.filter((s) => s.type === 'epic')

  function epicLabelFor(story: RequirementItem): string {
    const realEpic = epics.find((e) => e.id === story.parent_id)
    if (realEpic) return `Under ${realEpic.external_id} — ${realEpic.text}`
    const newEpic = epicSuggestions.find((e) => e.id === story.parent_id)
    if (newEpic) return `New epic: ${newEpic.text}`
    return ''
  }

  return (
    <div className="suggestions-panel">
      <div className="suggestions-panel__header">
        <h2 className="suggestions-panel__title">AI Suggestions</h2>
        <span className="suggestions-panel__count">{storySuggestions.length}</span>
      </div>

      {storySuggestions.length === 0 ? (
        <p className="suggestions-panel__empty">No open suggestions right now.</p>
      ) : (
        <ul className="suggestions-panel__list">
          {storySuggestions.map((story) => (
            <SuggestionCard
              key={story.id}
              story={story}
              epicLabel={epicLabelFor(story)}
              onAccept={onAccept}
              onDismiss={onDismiss}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function SuggestionCard({
  story,
  epicLabel,
  onAccept,
  onDismiss,
}: {
  story: RequirementItem
  epicLabel: string
  onAccept: (itemId: string) => Promise<void>
  onDismiss: (itemId: string) => Promise<void>
}) {
  const [busy, setBusy] = useState<'accept' | 'dismiss' | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run(kind: 'accept' | 'dismiss', action: (id: string) => Promise<void>) {
    setBusy(kind)
    setError(null)
    try {
      await action(story.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not ${kind}`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <li className="suggestion-card">
      <div className="suggestion-card__top">
        <Badge tone="accent">Suggestion</Badge>
        {epicLabel && <span className="suggestion-card__epic">{epicLabel}</span>}
      </div>
      <p className="suggestion-card__title">{story.text}</p>
      {story.description && <p className="suggestion-card__description">{story.description}</p>}
      {story.acceptance_criteria && story.acceptance_criteria.length > 0 && (
        <ul className="suggestion-card__ac-list">
          {story.acceptance_criteria.map((ac, i) => (
            <li key={i}>{ac.text}</li>
          ))}
        </ul>
      )}
      {error && <div className="suggestion-card__error">{error}</div>}
      <div className="suggestion-card__actions">
        <Button variant="secondary" size="sm" onClick={() => run('accept', onAccept)} disabled={busy !== null}>
          {busy === 'accept' ? 'Accepting…' : 'Accept'}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => run('dismiss', onDismiss)} disabled={busy !== null}>
          {busy === 'dismiss' ? 'Dismissing…' : 'Dismiss'}
        </Button>
      </div>
    </li>
  )
}
