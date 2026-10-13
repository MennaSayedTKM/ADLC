import { useState } from 'react'
import type { RequirementsDetail } from '../../api/types'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import './SuggestionsAside.css'

const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 } as const

interface SuggestionsAsideProps {
  detail: RequirementsDetail
  onSeeAll: () => void
  onDismissGap: (gapId: string) => Promise<void>
  onAccept: (itemId: string) => Promise<void>
  onDismiss: (itemId: string) => Promise<void>
}

/** A short list of what needs a decision next, with a way into the full Gaps & suggestions tab. */
export function SuggestionsAside({ detail, onSeeAll, onDismissGap, onAccept, onDismiss }: SuggestionsAsideProps) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const gaps = detail.gaps.filter((g) => g.status === 'open').sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
  const ideas = detail.suggestions.filter((s) => s.type === 'story')
  const total = gaps.length + ideas.length

  async function run(id: string, action: () => Promise<void>) {
    setBusy(id)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setBusy(null)
    }
  }

  return (
    <aside className="suggest-aside" aria-label="Suggestions">
      <header className="suggest-aside__header">
        <h2 className="suggest-aside__title">
          <Icon name="sparkles" size={16} /> Suggestions
        </h2>
        <span className="suggest-aside__count">{total} open</span>
      </header>

      {total === 0 && <p className="suggest-aside__empty">Nothing needs a decision right now.</p>}
      {error && <p className="suggest-aside__error">{error}</p>}

      <ul className="suggest-aside__list">
        {gaps.slice(0, 3).map((gap) => (
          <li key={gap.id} className="suggest-card">
            <div className="suggest-card__tag">
              <Badge tone={gap.severity === 'high' ? 'danger' : 'warning'} icon="alert">
                Gap{gap.severity === 'high' ? ' · high' : ''}
              </Badge>
              {gap.location && <span className="suggest-card__loc">§{gap.location}</span>}
            </div>
            <p className="suggest-card__body">{gap.description}</p>
            <div className="suggest-card__actions">
              <Button size="sm" variant="primary" onClick={onSeeAll}>
                Resolve
              </Button>
              <Button size="sm" variant="secondary" loading={busy === gap.id} onClick={() => run(gap.id, () => onDismissGap(gap.id))}>
                Dismiss
              </Button>
            </div>
          </li>
        ))}

        {ideas.slice(0, 2).map((idea) => (
          <li key={idea.id} className="suggest-card">
            <div className="suggest-card__tag">
              <Badge tone="info" icon="sparkles">
                Idea
              </Badge>
            </div>
            <p className="suggest-card__title">{idea.text}</p>
            {idea.description && <p className="suggest-card__body">{idea.description}</p>}
            <div className="suggest-card__actions">
              <Button size="sm" variant="primary" loading={busy === idea.id} onClick={() => run(idea.id, () => onAccept(idea.id))}>
                Add story
              </Button>
              <Button size="sm" variant="secondary" disabled={busy === idea.id} onClick={() => run(idea.id, () => onDismiss(idea.id))}>
                Dismiss
              </Button>
            </div>
          </li>
        ))}
      </ul>

      {total > 0 && (
        <button type="button" className="link-button" onClick={onSeeAll}>
          See all in Gaps &amp; suggestions
        </button>
      )}
    </aside>
  )
}
