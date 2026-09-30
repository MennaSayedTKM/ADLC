import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { StyleBrief, UxPrompt, UxPromptMode, UxPromptSources } from '../api/types'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { Banner } from './ui/Banner'
import './UxPromptGenerator.css'

const MODES: { value: UxPromptMode; label: string; hint: string }[] = [
  {
    value: 'foundation',
    label: 'New platform',
    hint: 'Design system, app shell and the first flows. Use once per product.',
  },
  {
    value: 'new_feature',
    label: 'New feature',
    hint: 'Screens for a feature in a product whose design system already exists.',
  },
  {
    value: 'edit_existing',
    label: 'Edit existing',
    hint: 'A targeted change to screens that already exist. Everything else stays untouched.',
  },
]

interface Props {
  projectId: string
  sources: UxPromptSources
  onGenerated: (prompt: UxPrompt, refreshedBrief: StyleBrief) => void
}

export function UxPromptGenerator({ projectId, sources, onGenerated }: Props) {
  const document = sources.document
  const [epicId, setEpicId] = useState<string>(sources.epics[0]?.epic.id ?? '')
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(sources.epics[0]?.stories.map((s) => s.id) ?? []),
  )
  const [mode, setMode] = useState<UxPromptMode>(sources.suggested_mode)
  const [brief, setBrief] = useState<StyleBrief>(sources.style_brief)
  const [screenshot, setScreenshot] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const epic = useMemo(() => sources.epics.find((e) => e.epic.id === epicId), [sources.epics, epicId])

  function chooseEpic(id: string) {
    setEpicId(id)
    setSelected(new Set(sources.epics.find((e) => e.epic.id === id)?.stories.map((s) => s.id) ?? []))
  }

  function toggleStory(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function setField<K extends keyof StyleBrief>(key: K, value: StyleBrief[K]) {
    setBrief((prev) => ({ ...prev, [key]: value }))
  }

  function chooseMode(next: UxPromptMode) {
    setMode(next)
    if (next !== 'edit_existing') setScreenshot(null)
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault()
    if (!document || !epic || selected.size === 0) return
    setBusy(true)
    setError(null)
    try {
      const prompt = await api.generateUxPrompt(projectId, {
        documentId: document.id,
        epicId: epic.epic.id,
        storyIds: epic.stories.filter((s) => selected.has(s.id)).map((s) => s.id),
        mode,
        styleBrief: brief,
        screenshot,
      })
      const refreshed = (await api.getUxPromptSources(projectId)).style_brief
      setBrief(refreshed)
      onGenerated(prompt, refreshed)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not generate the prompt')
    } finally {
      setBusy(false)
    }
  }

  const noDesignSystem = mode !== 'foundation' && !brief.design_tokens_summary

  return (
    <form className="ux-gen" onSubmit={handleGenerate}>
      <section className="ux-gen__step">
        <h2 className="ux-gen__step-title">
          <span className="ux-gen__step-num">1</span> Choose an epic
        </h2>
        <div className="ux-gen__epics" role="radiogroup" aria-label="Epic">
          {sources.epics.map(({ epic: e, stories }) => (
            <label
              key={e.id}
              className={`ux-gen__epic ${e.id === epicId ? 'ux-gen__epic--active' : ''}`}
            >
              <input
                type="radio"
                name="epic"
                checked={e.id === epicId}
                onChange={() => chooseEpic(e.id)}
                disabled={busy}
              />
              <span className="ux-gen__epic-id">{e.external_id}</span>
              <span className="ux-gen__epic-title">{e.text}</span>
              <Badge>{stories.length} {stories.length === 1 ? 'story' : 'stories'}</Badge>
            </label>
          ))}
        </div>
      </section>

      <section className="ux-gen__step">
        <h2 className="ux-gen__step-title">
          <span className="ux-gen__step-num">2</span> Stories to design
          <span className="ux-gen__step-aside">
            {selected.size} of {epic?.stories.length ?? 0} selected
          </span>
        </h2>
        {epic && epic.stories.length === 0 && (
          <p className="ux-gen__muted">This epic has no stories yet.</p>
        )}
        <ul className="ux-gen__stories">
          {epic?.stories.map((s) => (
            <li key={s.id}>
              <label className="ux-gen__story">
                <input
                  type="checkbox"
                  checked={selected.has(s.id)}
                  onChange={() => toggleStory(s.id)}
                  disabled={busy}
                />
                <span className="ux-gen__epic-id">{s.external_id}</span>
                <span>{s.text}</span>
              </label>
            </li>
          ))}
        </ul>
      </section>

      <section className="ux-gen__step">
        <h2 className="ux-gen__step-title">
          <span className="ux-gen__step-num">3</span> What is this prompt for?
        </h2>
        <div className="ux-gen__modes" role="radiogroup" aria-label="Prompt mode">
          {MODES.map((m) => (
            <label
              key={m.value}
              className={`ux-gen__mode ${m.value === mode ? 'ux-gen__mode--active' : ''}`}
            >
              <input
                type="radio"
                name="mode"
                checked={m.value === mode}
                onChange={() => chooseMode(m.value)}
                disabled={busy}
              />
              <span className="ux-gen__mode-label">
                {m.label}
                {m.value === sources.suggested_mode && <Badge tone="accent">Suggested</Badge>}
              </span>
              <span className="ux-gen__mode-hint">{m.hint}</span>
            </label>
          ))}
        </div>

        {noDesignSystem && (
          <Banner tone="warning">
            No design system is saved for this project yet, so Figma will be asked to match the
            look of your existing files. Generate a “New platform” prompt first, or paste a design
            system summary below, for more consistent results.
          </Banner>
        )}

        {mode === 'edit_existing' && (
          <div className="ux-gen__field">
            <label className="ux-gen__label" htmlFor="ux-screenshot">
              Screenshot of the current screen <span className="ux-gen__optional">optional</span>
            </label>
            <input
              id="ux-screenshot"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => setScreenshot(e.target.files?.[0] ?? null)}
              disabled={busy}
            />
            <p className="ux-gen__muted">
              It is described once by AI so the edit instructions point at real elements. The image
              itself is not stored.
            </p>
          </div>
        )}
      </section>

      <section className="ux-gen__step">
        <details className="ux-gen__brief" open={mode === 'foundation'}>
          <summary className="ux-gen__step-title ux-gen__summary">
            <span className="ux-gen__step-num">4</span> Style brief
            <span className="ux-gen__step-aside">optional · saved for this project</span>
          </summary>

          <div className="ux-gen__grid">
            <Field label="Reference brand or feel" wide>
              <input
                value={brief.reference_brand ?? ''}
                onChange={(e) => setField('reference_brand', e.target.value)}
                placeholder="e.g. Apple — clarity, whitespace, one accent color"
                disabled={busy}
              />
            </Field>
            <Field label="Primary brand color">
              <input
                value={brief.primary_color ?? ''}
                onChange={(e) => setField('primary_color', e.target.value)}
                placeholder="#0A66FF"
                disabled={busy}
              />
            </Field>
            <Field label="Tone">
              <input
                value={brief.tone ?? ''}
                onChange={(e) => setField('tone', e.target.value)}
                placeholder="calm, precise, professional"
                disabled={busy}
              />
            </Field>
            <Field label="Appearance">
              <select
                value={brief.appearance ?? ''}
                onChange={(e) => setField('appearance', (e.target.value || null) as StyleBrief['appearance'])}
                disabled={busy}
              >
                <option value="">Default</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
                <option value="both">Light and dark</option>
              </select>
            </Field>
            <Field label="Platform">
              <select
                value={brief.platform ?? ''}
                onChange={(e) => setField('platform', (e.target.value || null) as StyleBrief['platform'])}
                disabled={busy}
              >
                <option value="">Default</option>
                <option value="web">Web app</option>
                <option value="mobile">Mobile app</option>
                <option value="both">Web and mobile</option>
              </select>
            </Field>
            <Field label="Logo and brand notes" wide>
              <textarea
                rows={2}
                value={brief.brand_notes ?? ''}
                onChange={(e) => setField('brand_notes', e.target.value)}
                placeholder="e.g. Wordmark top-left on the sidebar; avoid green; rounded corners"
                disabled={busy}
              />
            </Field>
            {mode !== 'foundation' && (
              <Field label="Saved design system summary" wide>
                <textarea
                  rows={3}
                  value={brief.design_tokens_summary ?? ''}
                  onChange={(e) => setField('design_tokens_summary', e.target.value)}
                  placeholder="Filled in automatically by a New platform prompt. You can also paste your own: colors, fonts, spacing, shell layout, component names."
                  disabled={busy}
                />
              </Field>
            )}
          </div>
        </details>
      </section>

      {error && <Banner tone="danger">{error}</Banner>}

      <div className="ux-gen__actions">
        <Button
          type="submit"
          variant="primary"
          disabled={busy || !document || !epic || selected.size === 0}
        >
          {busy ? 'Generating prompt…' : 'Generate prompt'}
        </Button>
        <span className="ux-gen__muted">
          From {document ? `requirements v${document.version}` : 'an approved version'}
        </span>
      </div>
    </form>
  )
}

function Field({ label, wide, children }: { label: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <label className={`ux-gen__field ${wide ? 'ux-gen__field--wide' : ''}`}>
      <span className="ux-gen__label">{label}</span>
      {children}
    </label>
  )
}
