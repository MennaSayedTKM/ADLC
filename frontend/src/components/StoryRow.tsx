import { useState } from 'react'
import { api } from '../api/client'
import type { AcceptanceCriterion, ErrorHandlingEntry, ItemFields, RequirementItem, Scenario } from '../api/types'
import { ProvenanceBadge } from './ProvenanceBadge'
import { Button } from './ui/Button'
import './StoryRow.css'

interface StoryRowProps {
  story: RequirementItem
  onSave: (itemId: string, fields: ItemFields) => Promise<void>
  onDelete: (itemId: string) => Promise<void>
  projectId: string
  docId: string
}

const TBD_PATTERN = /\[TBD[^\]]*\]/i

function highlightTbd(text: string): (string | JSX.Element)[] {
  const parts = text.split(TBD_PATTERN)
  const matches = text.match(new RegExp(TBD_PATTERN, 'gi')) ?? []
  const out: (string | JSX.Element)[] = []
  parts.forEach((part, i) => {
    out.push(part)
    if (matches[i]) {
      out.push(
        <mark
          key={i}
          className="tbd-mark"
          title="The source document didn't specify exact wording here — needs real copy from design/eng before this is implementation-ready."
        >
          {matches[i]}
        </mark>,
      )
    }
  })
  return out
}

type AiField = 'acceptance_criterion' | 'scenario' | 'error_handling'

const AI_FIELD_LABEL: Record<AiField, string> = {
  acceptance_criterion: 'the criterion you want — the AI will phrase it',
  scenario: 'the scenario you want — the AI will write it as Given/When/Then',
  error_handling: 'the error case you want handled',
}

export function StoryRow({ story, onSave, onDelete, projectId, docId }: StoryRowProps) {
  const [editing, setEditing] = useState(false)
  const [acExpanded, setAcExpanded] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const [text, setText] = useState(story.text)
  const [description, setDescription] = useState(story.description ?? '')
  const [acItems, setAcItems] = useState<AcceptanceCriterion[]>(story.acceptance_criteria ?? [])
  const [scenarioItems, setScenarioItems] = useState<Scenario[]>(story.scenarios ?? [])
  const [errorItems, setErrorItems] = useState<ErrorHandlingEntry[]>(story.error_handling ?? [])

  const [aiOpenField, setAiOpenField] = useState<AiField | null>(null)
  const [aiSubject, setAiSubject] = useState('')
  const [aiBusy, setAiBusy] = useState(false)
  const [aiError, setAiError] = useState<string | null>(null)

  function toggleAi(field: AiField) {
    setAiOpenField((cur) => (cur === field ? null : field))
    setAiSubject('')
    setAiError(null)
  }

  async function handleGenerateAi(field: AiField) {
    if (!aiSubject.trim()) return
    setAiBusy(true)
    setAiError(null)
    try {
      const draft = await api.generateItemDraft(projectId, docId, {
        kind: field,
        subject: aiSubject.trim(),
        parent_id: story.id,
      })
      if (field === 'acceptance_criterion' && 'text' in draft) {
        setAcItems((items) => [...items, { text: draft.text, out_of_scope: false }])
      } else if (field === 'scenario' && 'given' in draft) {
        setScenarioItems((items) => [...items, draft])
      } else if (field === 'error_handling' && 'condition' in draft) {
        setErrorItems((items) => [...items, draft])
      }
      setAiOpenField(null)
      setAiSubject('')
    } catch (err) {
      setAiError(err instanceof Error ? err.message : 'Could not generate')
    } finally {
      setAiBusy(false)
    }
  }

  const acCount = story.acceptance_criteria?.length ?? 0
  const scenarios = story.scenarios ?? []
  const errorHandling = story.error_handling ?? []
  const tbdCount = [...scenarios.flatMap((s) => [s.given, s.when, s.then]), ...errorHandling.map((e) => e.message)].filter(
    (t) => TBD_PATTERN.test(t),
  ).length

  function startEdit() {
    setText(story.text)
    setDescription(story.description ?? '')
    setAcItems(story.acceptance_criteria ?? [])
    setScenarioItems(story.scenarios ?? [])
    setErrorItems(story.error_handling ?? [])
    setError(null)
    setAiOpenField(null)
    setAiSubject('')
    setAiError(null)
    setEditing(true)
  }

  async function handleSave() {
    setBusy(true)
    setError(null)
    try {
      await onSave(story.id, {
        text: text.trim(),
        description: description.trim(),
        acceptance_criteria: acItems.filter((ac) => ac.text.trim()),
        scenarios: scenarioItems.filter((s) => s.title.trim() || s.given.trim() || s.when.trim() || s.then.trim()),
        error_handling: errorItems.filter((e) => e.condition.trim() || e.message.trim()),
      })
      setEditing(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete story "${story.text}"? This can't be undone.`)) return
    setDeleting(true)
    setError(null)
    try {
      await onDelete(story.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete')
      setDeleting(false)
    }
  }

  function AiAssistRow({ field, label }: { field: AiField; label: string }) {
    return (
      <>
        <div className="story-row__add-row">
          <button
            type="button"
            className="story-row__add-btn"
            onClick={() => {
              if (field === 'acceptance_criterion') setAcItems((items) => [...items, { text: '', out_of_scope: false }])
              else if (field === 'scenario')
                setScenarioItems((items) => [...items, { title: '', given: '', when: '', then: '', source_reference: null }])
              else setErrorItems((items) => [...items, { condition: '', message: '' }])
            }}
          >
            {label}
          </button>
          <button type="button" className="story-row__add-btn story-row__add-btn--ai" onClick={() => toggleAi(field)}>
            ✨ Add with AI
          </button>
        </div>
        {aiOpenField === field && (
          <div className="story-row__ai-ac-form">
            <input
              className="story-row__editor-input"
              autoFocus
              placeholder={`Describe ${AI_FIELD_LABEL[field]}`}
              value={aiSubject}
              onChange={(e) => setAiSubject(e.target.value)}
              disabled={aiBusy}
            />
            {aiError && <div className="story-row__error">{aiError}</div>}
            <div className="story-row__ai-ac-actions">
              <Button
                type="button"
                variant="primary"
                size="sm"
                onClick={() => handleGenerateAi(field)}
                disabled={aiBusy || !aiSubject.trim()}
              >
                {aiBusy ? 'Generating…' : 'Generate'}
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setAiOpenField(null)} disabled={aiBusy}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </>
    )
  }

  if (editing) {
    return (
      <li className="story-row story-row--editing">
        <span className="story-row__id">{story.external_id}</span>
        <div className="story-row__edit-body">
          <label className="story-row__field-label">Title</label>
          <textarea
            className="story-row__textarea"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            autoFocus
          />

          <label className="story-row__field-label">Description</label>
          <textarea
            className="story-row__textarea"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="As a [role], I want [capability], so that [benefit]."
          />

          <label className="story-row__field-label">Acceptance criteria</label>
          <div className="story-row__editor-list">
            {acItems.map((ac, i) => (
              <div key={i} className="story-row__ac-edit-row">
                <input
                  type="checkbox"
                  checked={ac.out_of_scope}
                  title="Out of scope"
                  onChange={(e) =>
                    setAcItems((items) => items.map((it, j) => (j === i ? { ...it, out_of_scope: e.target.checked } : it)))
                  }
                />
                <input
                  className="story-row__editor-input"
                  value={ac.text}
                  placeholder="Acceptance criterion"
                  onChange={(e) =>
                    setAcItems((items) => items.map((it, j) => (j === i ? { ...it, text: e.target.value } : it)))
                  }
                />
                <button
                  type="button"
                  className="story-row__remove-btn"
                  onClick={() => setAcItems((items) => items.filter((_, j) => j !== i))}
                  aria-label="Remove criterion"
                >
                  ×
                </button>
              </div>
            ))}
            <AiAssistRow field="acceptance_criterion" label="+ Add criterion" />
          </div>

          <label className="story-row__field-label">Scenarios</label>
          <div className="story-row__editor-list">
            {scenarioItems.map((sc, i) => (
              <div key={i} className="story-row__scenario-edit-card">
                <div className="story-row__scenario-edit-header">
                  <input
                    className="story-row__editor-input"
                    value={sc.title}
                    placeholder="Scenario title"
                    onChange={(e) =>
                      setScenarioItems((items) => items.map((it, j) => (j === i ? { ...it, title: e.target.value } : it)))
                    }
                  />
                  <button
                    type="button"
                    className="story-row__remove-btn"
                    onClick={() => setScenarioItems((items) => items.filter((_, j) => j !== i))}
                    aria-label="Remove scenario"
                  >
                    ×
                  </button>
                </div>
                {(['given', 'when', 'then'] as const).map((field) => (
                  <input
                    key={field}
                    className="story-row__editor-input"
                    value={sc[field]}
                    placeholder={field[0].toUpperCase() + field.slice(1)}
                    onChange={(e) =>
                      setScenarioItems((items) =>
                        items.map((it, j) => (j === i ? { ...it, [field]: e.target.value } : it)),
                      )
                    }
                  />
                ))}
                <input
                  className="story-row__editor-input story-row__editor-input--ref"
                  value={sc.source_reference ?? ''}
                  placeholder="Source reference (e.g. 4.1.A)"
                  onChange={(e) =>
                    setScenarioItems((items) =>
                      items.map((it, j) => (j === i ? { ...it, source_reference: e.target.value } : it)),
                    )
                  }
                />
              </div>
            ))}
            <AiAssistRow field="scenario" label="+ Add scenario" />
          </div>

          <label className="story-row__field-label">Error handling</label>
          <div className="story-row__editor-list">
            {errorItems.map((eh, i) => (
              <div key={i} className="story-row__eh-edit-row">
                <input
                  className="story-row__editor-input"
                  value={eh.condition}
                  placeholder="Condition"
                  onChange={(e) =>
                    setErrorItems((items) => items.map((it, j) => (j === i ? { ...it, condition: e.target.value } : it)))
                  }
                />
                <input
                  className="story-row__editor-input"
                  value={eh.message}
                  placeholder="Message"
                  onChange={(e) =>
                    setErrorItems((items) => items.map((it, j) => (j === i ? { ...it, message: e.target.value } : it)))
                  }
                />
                <button
                  type="button"
                  className="story-row__remove-btn"
                  onClick={() => setErrorItems((items) => items.filter((_, j) => j !== i))}
                  aria-label="Remove error case"
                >
                  ×
                </button>
              </div>
            ))}
            <AiAssistRow field="error_handling" label="+ Add error case" />
          </div>

          {error && <div className="story-row__error">{error}</div>}
          <div className="story-row__edit-actions">
            <Button variant="primary" size="sm" onClick={handleSave} disabled={busy || !text.trim()}>
              {busy ? 'Saving…' : 'Save'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" size="sm" onClick={handleDelete} disabled={busy || deleting}>
              {deleting ? 'Deleting…' : 'Delete story'}
            </Button>
          </div>
        </div>
      </li>
    )
  }

  return (
    <li className="story-row" onClick={startEdit}>
      <span className="story-row__id">{story.external_id}</span>
      <div className="story-row__body">
        <div className="story-row__title-row">
          <p className="story-row__text">{story.text}</p>
          <ProvenanceBadge origin={story.origin} />
          {tbdCount > 0 && <span className="story-row__tbd-badge">{tbdCount} need input</span>}
        </div>
        {story.description && <p className="story-row__description">{story.description}</p>}

        <div
          className={`story-row__ac ${acCount === 0 ? 'story-row__ac--empty' : ''}`}
          onClick={(e) => {
            e.stopPropagation()
            if (acCount > 0) setAcExpanded((v) => !v)
            else startEdit()
          }}
        >
          <span className={`story-row__ac-chevron ${acExpanded ? '' : 'story-row__ac-chevron--collapsed'}`}>
            {acCount > 0 ? '▾' : ''}
          </span>
          <span className="story-row__ac-heading">
            Acceptance criteria {acCount > 0 ? `(${acCount})` : '— none yet, click to add'}
          </span>
        </div>

        {acExpanded && acCount > 0 && (
          <ul className="story-row__ac-list">
            {story.acceptance_criteria!.map((ac, i) => (
              <li key={i} className={`story-row__ac-item ${ac.out_of_scope ? 'story-row__ac-item--out-of-scope' : ''}`}>
                {ac.text}
                {ac.out_of_scope && <span className="story-row__ac-badge">Out of scope</span>}
              </li>
            ))}
          </ul>
        )}

        {scenarios.length > 0 && (
          <div className="story-row__section">
            <span className="story-row__section-heading">Scenarios ({scenarios.length})</span>
            <ul className="story-row__scenario-list">
              {scenarios.map((sc, i) => (
                <li key={i} className="story-row__scenario-item">
                  <p className="story-row__scenario-title">
                    {sc.title}
                    {sc.source_reference && (
                      <span className="story-row__source-ref" title="Source reference">
                        {sc.source_reference}
                      </span>
                    )}
                  </p>
                  <p>
                    <span className="story-row__scenario-label">Given</span> {highlightTbd(sc.given)}
                  </p>
                  <p>
                    <span className="story-row__scenario-label">When</span> {highlightTbd(sc.when)}
                  </p>
                  <p>
                    <span className="story-row__scenario-label">Then</span> {highlightTbd(sc.then)}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}

        {errorHandling.length > 0 && (
          <div className="story-row__section">
            <span className="story-row__section-heading">Error handling ({errorHandling.length})</span>
            <ul className="story-row__eh-list">
              {errorHandling.map((eh, i) => (
                <li key={i} className="story-row__eh-item">
                  <span className="story-row__eh-condition">{eh.condition}</span>
                  <span className="story-row__eh-arrow">→</span>
                  {highlightTbd(eh.message)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <span className="story-row__edit-hint">Edit</span>
    </li>
  )
}
