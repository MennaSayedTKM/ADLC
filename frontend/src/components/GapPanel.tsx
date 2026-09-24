import { useState } from 'react'
import { api } from '../api/client'
import type { Gap, ItemFields, RequirementItem, StoryDraft } from '../api/types'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import './GapPanel.css'

const SEVERITY_TONE = { high: 'danger', medium: 'warning', low: 'neutral' } as const
const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 } as const

/**
 * Best-guess epic for a gap, from source_reference matching alone (no AI
 * call needed — the data to do this cheaply already exists). A gap's
 * location usually cites the same section numbering as an epic's own
 * source_reference (e.g. gap "4.7" against epic source_reference "4.1"),
 * so an exact match or a prefix relationship either way is a strong
 * signal; falls back to the first epic when nothing lines up.
 */
function recommendEpicId(gap: Gap, epics: RequirementItem[]): string {
  const loc = gap.location?.trim()
  if (loc) {
    const exact = epics.find((e) => e.source_reference?.trim() === loc)
    if (exact) return exact.id
    const epicIsPrefixOfLoc = epics.find((e) => e.source_reference && loc.startsWith(e.source_reference.trim()))
    if (epicIsPrefixOfLoc) return epicIsPrefixOfLoc.id
    const locIsPrefixOfEpic = epics.find((e) => e.source_reference && e.source_reference.trim().startsWith(loc))
    if (locIsPrefixOfEpic) return locIsPrefixOfEpic.id
  }
  return epics[0]?.id ?? ''
}

interface GapPanelProps {
  projectId: string
  docId: string
  gaps: Gap[]
  epics: RequirementItem[]
  onSetStatus: (gapId: string, status: 'dismissed' | 'open') => Promise<void>
  onResolveAsStory: (gapId: string, parentId: string, fields?: ItemFields) => Promise<void>
}

export function GapPanel({ projectId, docId, gaps, epics, onSetStatus, onResolveAsStory }: GapPanelProps) {
  const sorted = [...gaps].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])

  return (
    <div className="gap-panel">
      <div className="gap-panel__header">
        <h2 className="gap-panel__title">Gaps</h2>
        <span className="gap-panel__count">{gaps.length}</span>
      </div>

      {gaps.length === 0 ? (
        <p className="gap-panel__empty">No gaps flagged — extraction found no ambiguities.</p>
      ) : (
        <ul className="gap-panel__list">
          {sorted.map((gap) => (
            <GapCard
              key={gap.id}
              gap={gap}
              epics={epics}
              projectId={projectId}
              docId={docId}
              onSetStatus={onSetStatus}
              onResolveAsStory={onResolveAsStory}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

type Mode = 'manual' | 'ai'

function GapCard({
  gap,
  epics,
  projectId,
  docId,
  onSetStatus,
  onResolveAsStory,
}: {
  gap: Gap
  epics: RequirementItem[]
  projectId: string
  docId: string
  onSetStatus: (gapId: string, status: 'dismissed' | 'open') => Promise<void>
  onResolveAsStory: (gapId: string, parentId: string, fields?: ItemFields) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [mode, setMode] = useState<Mode>('manual')
  const [selectedEpicId, setSelectedEpicId] = useState(() => recommendEpicId(gap, epics))
  const [draft, setDraft] = useState<StoryDraft | null>(null)
  const [error, setError] = useState<string | null>(null)

  const recommendedEpicId = recommendEpicId(gap, epics)

  function startResolving() {
    setSelectedEpicId(recommendedEpicId)
    setMode('manual')
    setDraft(null)
    setError(null)
    setResolving(true)
  }

  async function handleSetStatus(status: 'dismissed' | 'open') {
    setBusy(true)
    setError(null)
    try {
      await onSetStatus(gap.id, status)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update gap')
    } finally {
      setBusy(false)
    }
  }

  async function handleGenerateDraft(regenerate = false) {
    if (!selectedEpicId) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.generateItemDraft(projectId, docId, {
        kind: 'story',
        subject: gap.description,
        parent_id: selectedEpicId,
        previous_draft: regenerate && draft ? draft : undefined,
      })
      if ('description' in result) setDraft(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not generate a draft')
    } finally {
      setBusy(false)
    }
  }

  async function handleConfirmManual() {
    if (!selectedEpicId) return
    setBusy(true)
    setError(null)
    try {
      await onResolveAsStory(gap.id, selectedEpicId)
      setResolving(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not resolve gap')
    } finally {
      setBusy(false)
    }
  }

  async function handleConfirmDraft() {
    if (!selectedEpicId || !draft) return
    setBusy(true)
    setError(null)
    try {
      // draft.title maps to ItemFields.text (the story's title field) — a
      // plain spread would leave `title` sitting unused on the object and
      // `text` unset, silently falling back to the gap's own description as
      // the story's title on the backend instead of the AI-drafted one.
      await onResolveAsStory(gap.id, selectedEpicId, {
        text: draft.title,
        description: draft.description,
        scenarios: draft.scenarios,
        acceptance_criteria: draft.acceptance_criteria,
        error_handling: draft.error_handling,
        origin: 'pm_ai_assisted',
      })
      setResolving(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not resolve gap')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className={`gap-card gap-card--${gap.status} gap-card--severity-${gap.severity}`}>
      <div className="gap-card__top">
        <Badge tone={SEVERITY_TONE[gap.severity]}>{gap.severity}</Badge>
        {gap.location ? (
          <span className="gap-card__page">{gap.location}</span>
        ) : (
          gap.page !== null && <span className="gap-card__page">p.{gap.page}</span>
        )}
      </div>
      <p className="gap-card__description">{gap.description}</p>

      {resolving ? (
        <div className="gap-card__resolve-form">
          {epics.length === 0 ? (
            <p className="gap-card__resolve-hint">Add an epic first — a gap becomes a story under one.</p>
          ) : (
            <>
              <select
                className="gap-card__epic-select"
                value={selectedEpicId}
                onChange={(e) => {
                  setSelectedEpicId(e.target.value)
                  setDraft(null)
                }}
                disabled={busy}
              >
                {epics.map((epic) => (
                  <option key={epic.id} value={epic.id}>
                    {epic.external_id} — {epic.text}
                    {epic.id === recommendedEpicId ? ' (recommended)' : ''}
                  </option>
                ))}
              </select>

              <div className="gap-card__mode-toggle" role="tablist">
                <button
                  type="button"
                  role="tab"
                  className={`gap-card__mode-btn ${mode === 'manual' ? 'gap-card__mode-btn--active' : ''}`}
                  onClick={() => {
                    setMode('manual')
                    setDraft(null)
                  }}
                  disabled={busy}
                >
                  Manual
                </button>
                <button
                  type="button"
                  role="tab"
                  className={`gap-card__mode-btn ${mode === 'ai' ? 'gap-card__mode-btn--active' : ''}`}
                  onClick={() => setMode('ai')}
                  disabled={busy}
                >
                  ✨ AI-assisted
                </button>
              </div>

              {mode === 'manual' && (
                <div className="gap-card__actions">
                  <Button variant="secondary" size="sm" onClick={handleConfirmManual} disabled={busy}>
                    {busy ? 'Resolving…' : 'Confirm'}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setResolving(false)} disabled={busy}>
                    Cancel
                  </Button>
                </div>
              )}

              {mode === 'ai' && !draft && (
                <div className="gap-card__actions">
                  <Button variant="secondary" size="sm" onClick={() => handleGenerateDraft(false)} disabled={busy}>
                    {busy ? 'Generating…' : 'Generate story from this gap'}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setResolving(false)} disabled={busy}>
                    Cancel
                  </Button>
                </div>
              )}

              {mode === 'ai' && draft && (
                <div className="gap-card__draft-preview">
                  <div className="gap-card__draft-badge">AI-drafted — review before resolving</div>
                  <p className="gap-card__draft-title">{draft.title}</p>
                  <p className="gap-card__draft-description">{draft.description}</p>
                  <p className="gap-card__draft-summary">
                    {draft.scenarios.length} scenario{draft.scenarios.length === 1 ? '' : 's'},{' '}
                    {draft.acceptance_criteria.length} acceptance criteri
                    {draft.acceptance_criteria.length === 1 ? 'on' : 'a'} — editable after resolving.
                  </p>
                  <div className="gap-card__actions">
                    <Button variant="secondary" size="sm" onClick={handleConfirmDraft} disabled={busy}>
                      {busy ? 'Resolving…' : 'Resolve with this story'}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => handleGenerateDraft(true)} disabled={busy}>
                      {busy ? 'Regenerating…' : 'Regenerate'}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setResolving(false)} disabled={busy}>
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        <div className="gap-card__actions">
          {gap.status === 'open' && (
            <>
              <Button variant="secondary" size="sm" onClick={startResolving} disabled={busy}>
                Resolve as story
              </Button>
              <Button variant="ghost" size="sm" onClick={() => handleSetStatus('dismissed')} disabled={busy}>
                Dismiss
              </Button>
            </>
          )}
          {gap.status === 'resolved' && (
            <span className="gap-card__status-label gap-card__status-label--resolved">✓ Resolved as story</span>
          )}
          {gap.status === 'dismissed' && (
            <>
              <span className="gap-card__status-label">Dismissed</span>
              <Button variant="ghost" size="sm" onClick={() => handleSetStatus('open')} disabled={busy}>
                Reopen
              </Button>
            </>
          )}
        </div>
      )}

      {error && <div className="gap-card__error">{error}</div>}
    </li>
  )
}
