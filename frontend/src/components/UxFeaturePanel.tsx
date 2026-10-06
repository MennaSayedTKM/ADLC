import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { UxPrompt, UxPromptSources } from '../api/types'
import { Badge } from './ui/Badge'
import { Banner } from './ui/Banner'
import { Button } from './ui/Button'
import './UxFeaturePanel.css'

type FeatureMode = 'new_feature' | 'edit_existing'
type RunStatus = 'waiting' | 'running' | 'done' | 'failed'

interface Props {
  projectId: string
  sources: UxPromptSources
  onPrompt: (prompt: UxPrompt) => void
  onFinished: () => void
}

export function UxFeaturePanel({ projectId, sources, onPrompt, onFinished }: Props) {
  const document = sources.document!
  const [mode, setMode] = useState<FeatureMode>(sources.suggested_mode === 'edit_existing' ? 'edit_existing' : 'new_feature')
  const [order, setOrder] = useState<string[]>(sources.suggested_order)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [excluded, setExcluded] = useState<Set<string>>(new Set()) // story ids the PM unticked
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [screenshot, setScreenshot] = useState<File | null>(null)
  const [progress, setProgress] = useState<{ epic: string; status: RunStatus; error?: string }[]>([])
  const [running, setRunning] = useState(false)

  const epics = new Map(sources.epics.map((e) => [e.epic.external_id, e]))
  const status = new Map(sources.sitemap.map((s) => [s.epic_external_id, s.status]))
  const relations = new Map(sources.feature_map.map((f) => [f.epic_external_id, f]))

  // Keep the PM's ordering when sources refresh (e.g. after a prompt is saved),
  // but pick up epics that are new and drop ones that are gone.
  useEffect(() => {
    setOrder((prev) => {
      const known = prev.filter((id) => sources.suggested_order.includes(id))
      return [...known, ...sources.suggested_order.filter((id) => !known.includes(id))]
    })
  }, [sources.suggested_order])

  const blocked = mode === 'new_feature' && !sources.has_blueprint && !sources.has_design_system
  const chosen = order.filter((id) => selected.has(id))
  const storiesOf = (id: string) => (epics.get(id)?.stories ?? []).filter((s) => !excluded.has(s.id))
  const canGenerate = !running && !blocked && chosen.length > 0 && chosen.every((id) => storiesOf(id).length > 0)

  function toggle(set: Set<string>, id: string): Set<string> {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  }

  function move(id: string, delta: -1 | 1) {
    setOrder((prev) => {
      const i = prev.indexOf(id)
      const j = i + delta
      if (i < 0 || j < 0 || j >= prev.length) return prev
      const next = [...prev]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }

  function chooseMode(next: FeatureMode) {
    setMode(next)
    if (next !== 'edit_existing') setScreenshot(null)
  }

  async function handleGenerate() {
    setRunning(true)
    setProgress(chosen.map((epic) => ({ epic, status: 'waiting' })))
    const setStatus = (epic: string, s: RunStatus, error?: string) =>
      setProgress((prev) => prev.map((p) => (p.epic === epic ? { ...p, status: s, error } : p)))

    // One request per epic, in order: each prompt is generated knowing the screens
    // the previous ones created. A failure doesn't stop the rest.
    for (const epicId of chosen) {
      setStatus(epicId, 'running')
      try {
        const prompt = await api.generateUxPrompt(projectId, {
          documentId: document.id,
          mode,
          styleBrief: {},
          epicId: epics.get(epicId)!.epic.id,
          storyIds: storiesOf(epicId).map((s) => s.id),
          screenshot: mode === 'edit_existing' && chosen.length === 1 ? screenshot : null,
        })
        onPrompt(prompt)
        setStatus(epicId, 'done')
      } catch (err) {
        setStatus(epicId, 'failed', err instanceof Error ? err.message : 'Could not generate this prompt')
      }
    }
    setRunning(false)
    setSelected(new Set())
    onFinished()
  }

  return (
    <section className="ux-feat">
      <header className="ux-feat__header">
        <h2 className="ux-feat__title">
          <span className="ux-feat__num">2</span> Features
        </h2>
        <span className="ux-feat__count">{chosen.length} selected</span>
      </header>
      <p className="ux-feat__hint">
        Each epic becomes its own prompt that fits into its navigation slot. Pick several to generate them one
        after another; the order below puts the features other features depend on first.
      </p>

      <div className="ux-feat__modes" role="radiogroup" aria-label="Prompt mode">
        {(
          [
            ['new_feature', 'New feature', 'Design the epic into its placeholder slot.'],
            ['edit_existing', 'Edit existing', 'A targeted change to screens that already exist.'],
          ] as const
        ).map(([value, label, hint]) => (
          <label key={value} className={`ux-feat__mode ${mode === value ? 'ux-feat__mode--active' : ''}`}>
            <input type="radio" name="feature-mode" checked={mode === value} onChange={() => chooseMode(value)} disabled={running} />
            <span className="ux-feat__mode-label">
              {label}
              {sources.suggested_mode === value && <Badge tone="accent">Suggested</Badge>}
            </span>
            <span className="ux-feat__mode-hint">{hint}</span>
          </label>
        ))}
      </div>

      {blocked && (
        <Banner tone="warning">
          Generate the platform blueprint first. New features are built to fit it, so they share one design system
          and navigation.
        </Banner>
      )}

      <div className="ux-feat__toolbar">
        <button
          type="button"
          className="ux-feat__link"
          onClick={() => setSelected(new Set(order.filter((id) => status.get(id) !== 'designed')))}
          disabled={running}
        >
          Select epics not designed yet
        </button>
        <button type="button" className="ux-feat__link" onClick={() => setSelected(new Set(order))} disabled={running}>
          Select all
        </button>
        <button type="button" className="ux-feat__link" onClick={() => setSelected(new Set())} disabled={running}>
          Clear
        </button>
      </div>

      <ol className="ux-feat__list">
        {order.map((id, index) => {
          const entry = epics.get(id)
          if (!entry) return null
          const stories = entry.stories
          const picked = stories.filter((s) => !excluded.has(s.id)).length
          const deps = relations.get(id)?.depends_on ?? []
          const open = expanded.has(id)
          return (
            <li key={id} className={`ux-feat__item ${selected.has(id) ? 'ux-feat__item--selected' : ''}`}>
              <div className="ux-feat__row">
                <label className="ux-feat__pick">
                  <input
                    type="checkbox"
                    checked={selected.has(id)}
                    onChange={() => setSelected((prev) => toggle(prev, id))}
                    disabled={running}
                    aria-label={`Include ${entry.epic.text}`}
                  />
                  <span className="ux-feat__order">{index + 1}</span>
                  <span className="ux-feat__id">{id}</span>
                  <span className="ux-feat__name">{entry.epic.text}</span>
                </label>
                <div className="ux-feat__meta">
                  {deps.length > 0 && <span className="ux-feat__dep">after {deps.join(', ')}</span>}
                  {status.get(id) === 'designed' && <Badge tone="success">Designed</Badge>}
                  <button
                    type="button"
                    className="ux-feat__stories-toggle"
                    onClick={() => setExpanded((prev) => toggle(prev, id))}
                    aria-expanded={open}
                  >
                    {picked}/{stories.length} {stories.length === 1 ? 'story' : 'stories'}
                  </button>
                  <button type="button" className="ux-feat__move" onClick={() => move(id, -1)} disabled={running || index === 0} aria-label={`Move ${entry.epic.text} up`} title="Move up">
                    ↑
                  </button>
                  <button type="button" className="ux-feat__move" onClick={() => move(id, 1)} disabled={running || index === order.length - 1} aria-label={`Move ${entry.epic.text} down`} title="Move down">
                    ↓
                  </button>
                </div>
              </div>
              {open && (
                <ul className="ux-feat__stories">
                  {stories.map((s) => (
                    <li key={s.id}>
                      <label className="ux-feat__story">
                        <input
                          type="checkbox"
                          checked={!excluded.has(s.id)}
                          onChange={() => setExcluded((prev) => toggle(prev, s.id))}
                          disabled={running}
                        />
                        <span className="ux-feat__id">{s.external_id}</span>
                        {s.text}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ol>

      {mode === 'edit_existing' && chosen.length === 1 && (
        <label className="ux-feat__screenshot">
          <span className="ux-feat__label">
            Screenshot of the current screen <span className="ux-feat__optional">optional</span>
          </span>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => setScreenshot(e.target.files?.[0] ?? null)}
            disabled={running}
          />
          <span className="ux-feat__hint">
            Described once by AI so the edit points at real elements. The image itself is not stored.
          </span>
        </label>
      )}

      {progress.length > 0 && (
        <ul className="ux-feat__progress" aria-live="polite">
          {progress.map((p) => (
            <li key={p.epic} className={`ux-feat__progress-item ux-feat__progress-item--${p.status}`}>
              <span className="ux-feat__id">{p.epic}</span>
              {epics.get(p.epic)?.epic.text}
              <span className="ux-feat__progress-status">
                {p.status === 'waiting' && 'Waiting'}
                {p.status === 'running' && 'Generating…'}
                {p.status === 'done' && 'Done'}
                {p.status === 'failed' && `Failed: ${p.error}`}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="ux-feat__actions">
        <Button type="button" variant="primary" onClick={handleGenerate} disabled={!canGenerate}>
          {running ? 'Generating…' : chosen.length > 1 ? `Generate ${chosen.length} prompts` : 'Generate prompt'}
        </Button>
        <span className="ux-feat__hint">
          Paste the prompts into the same Figma Make project, in the order shown, so each one builds on the last.
        </span>
      </div>
    </section>
  )
}
