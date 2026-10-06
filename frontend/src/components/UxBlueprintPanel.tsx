import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { StyleBrief, UxPrompt, UxPromptSources } from '../api/types'
import { StyleReferenceEditor } from './StyleReferenceEditor'
import { Badge } from './ui/Badge'
import { Banner } from './ui/Banner'
import { Button } from './ui/Button'
import './UxBlueprintPanel.css'

interface Props {
  projectId: string
  sources: UxPromptSources
  onBlueprint: (prompt: UxPrompt) => void
}

// Only the PM-editable fields are sent; sitemap / component list / feature map
// belong to blueprint generation.
function editable(brief: StyleBrief): StyleBrief {
  return {
    vision: brief.vision ?? '',
    target_users: brief.target_users ?? '',
    reference_brand: brief.reference_brand ?? '',
    primary_color: brief.primary_color ?? '',
    tone: brief.tone ?? '',
    appearance: brief.appearance ?? null,
    platform: brief.platform ?? null,
    brand_notes: brief.brand_notes ?? '',
    reference_styles: brief.reference_styles ?? [],
    design_tokens_summary: brief.design_tokens_summary ?? '',
  }
}

export function UxBlueprintPanel({ projectId, sources, onBlueprint }: Props) {
  const document = sources.document!
  const [brief, setBrief] = useState<StyleBrief>(() => editable(sources.style_brief))
  const [busy, setBusy] = useState<null | 'draft' | 'generate' | 'save'>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  // Regenerating rewrites the design system summary on the server — show it.
  const serverSummary = sources.style_brief.design_tokens_summary ?? ''
  useEffect(() => {
    setBrief((prev) => ({ ...prev, design_tokens_summary: serverSummary }))
  }, [serverSummary])

  const exists = sources.has_blueprint
  const missing = sources.epics_missing_from_blueprint
  const working = busy !== null

  function set<K extends keyof StyleBrief>(key: K, value: StyleBrief[K]) {
    setBrief((prev) => ({ ...prev, [key]: value }))
    setSaved(false)
  }

  async function run(kind: 'draft' | 'generate' | 'save', action: () => Promise<void>, fallback: string) {
    setBusy(kind)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback)
    } finally {
      setBusy(null)
    }
  }

  function handleDraftVision() {
    if (brief.vision?.trim() && !window.confirm('Replace the vision you wrote with an AI draft?')) return
    run(
      'draft',
      async () => {
        const drafted = await api.draftVision(projectId)
        setBrief((prev) => ({ ...prev, vision: drafted.vision, target_users: drafted.target_users }))
      },
      'Could not draft a vision',
    )
  }

  function handleSave() {
    run(
      'save',
      async () => {
        await api.saveStyleBrief(projectId, brief)
        setSaved(true)
      },
      'Could not save the brief',
    )
  }

  function handleGenerate() {
    if (exists && !window.confirm('Regenerating replaces the blueprint text, including any edits you made to it. Continue?')) {
      return
    }
    run(
      'generate',
      async () => {
        if (exists && sources.blueprint_prompt_id) {
          await api.saveStyleBrief(projectId, brief) // regenerate reads the saved brief
          onBlueprint(await api.regenerateUxPrompt(projectId, sources.blueprint_prompt_id))
        } else {
          onBlueprint(await api.generateUxPrompt(projectId, { documentId: document.id, mode: 'foundation', styleBrief: brief }))
        }
        setSaved(true)
      },
      'Could not generate the blueprint',
    )
  }

  return (
    <section className="ux-bp">
      <header className="ux-bp__header">
        <h2 className="ux-bp__title">
          <span className="ux-bp__num">1</span> Platform blueprint
        </h2>
        {exists ? <Badge tone="success">Ready</Badge> : <Badge>Not generated yet</Badge>}
      </header>
      <p className="ux-bp__hint">
        The base of the whole platform: its vision, design system, app shell and a navigation slot for every
        epic. Generate it once; every feature you add afterwards snaps into its slot, like building blocks.
      </p>

      {missing.length > 0 && (
        <Banner tone="warning">
          {missing.join(', ')} {missing.length === 1 ? 'was' : 'were'} approved after the blueprint was generated
          and {missing.length === 1 ? 'has' : 'have'} no navigation slot yet. Regenerate the blueprint to add
          {missing.length === 1 ? ' it' : ' them'}.
        </Banner>
      )}

      <div className="ux-bp__grid">
        <label className="ux-bp__field ux-bp__field--wide">
          <span className="ux-bp__label">
            Vision and purpose
            <button
              type="button"
              className="ux-bp__link"
              onClick={handleDraftVision}
              disabled={working}
            >
              {busy === 'draft' ? 'Drafting…' : 'Draft from requirements'}
            </button>
          </span>
          <textarea
            rows={4}
            value={brief.vision ?? ''}
            onChange={(e) => set('vision', e.target.value)}
            placeholder="What is this platform, who is it for, and what should it feel like? e.g. A calm, executive-grade workspace where the Strategy Office plans objectives and tracks progress."
            disabled={working}
          />
        </label>

        <label className="ux-bp__field ux-bp__field--wide">
          <span className="ux-bp__label">Who uses it</span>
          <input
            value={brief.target_users ?? ''}
            onChange={(e) => set('target_users', e.target.value)}
            placeholder="e.g. Strategy Office team, department heads, executives"
            disabled={working}
          />
        </label>

        <label className="ux-bp__field">
          <span className="ux-bp__label">Platform</span>
          <select
            value={brief.platform ?? ''}
            onChange={(e) => set('platform', (e.target.value || null) as StyleBrief['platform'])}
            disabled={working}
          >
            <option value="">Default</option>
            <option value="web">Web app</option>
            <option value="mobile">Mobile app</option>
            <option value="both">Web and mobile</option>
          </select>
        </label>
        <label className="ux-bp__field">
          <span className="ux-bp__label">Appearance</span>
          <select
            value={brief.appearance ?? ''}
            onChange={(e) => set('appearance', (e.target.value || null) as StyleBrief['appearance'])}
            disabled={working}
          >
            <option value="">Default</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
            <option value="both">Light and dark</option>
          </select>
        </label>
      </div>

      <div className="ux-bp__block">
        <h3 className="ux-bp__subtitle">Visual reference</h3>
        <StyleReferenceEditor
          projectId={projectId}
          references={brief.reference_styles ?? []}
          onChange={(refs) => set('reference_styles', refs)}
          disabled={working}
        />
      </div>

      <details className="ux-bp__more">
        <summary>More style options</summary>
        <div className="ux-bp__grid">
          <label className="ux-bp__field ux-bp__field--wide">
            <span className="ux-bp__label">Reference brand or feel</span>
            <input
              value={brief.reference_brand ?? ''}
              onChange={(e) => set('reference_brand', e.target.value)}
              placeholder="e.g. Apple: clarity, whitespace, one accent color (used when no website is given)"
              disabled={working}
            />
          </label>
          <label className="ux-bp__field">
            <span className="ux-bp__label">Primary brand color</span>
            <input
              value={brief.primary_color ?? ''}
              onChange={(e) => set('primary_color', e.target.value)}
              placeholder="#0A66FF"
              disabled={working}
            />
          </label>
          <label className="ux-bp__field">
            <span className="ux-bp__label">Tone</span>
            <input
              value={brief.tone ?? ''}
              onChange={(e) => set('tone', e.target.value)}
              placeholder="calm, precise, professional"
              disabled={working}
            />
          </label>
          <label className="ux-bp__field ux-bp__field--wide">
            <span className="ux-bp__label">Logo and brand notes</span>
            <textarea
              rows={2}
              value={brief.brand_notes ?? ''}
              onChange={(e) => set('brand_notes', e.target.value)}
              placeholder="e.g. Wordmark top-left on the sidebar; avoid green; rounded corners"
              disabled={working}
            />
          </label>
          {(exists || sources.has_design_system) && (
            <label className="ux-bp__field ux-bp__field--wide">
              <span className="ux-bp__label">Design system summary (sent with every feature prompt)</span>
              <textarea
                rows={3}
                value={brief.design_tokens_summary ?? ''}
                onChange={(e) => set('design_tokens_summary', e.target.value)}
                disabled={working}
              />
            </label>
          )}
        </div>
      </details>

      {exists && sources.sitemap.length > 0 && (
        <div className="ux-bp__block">
          <h3 className="ux-bp__subtitle">Navigation slots</h3>
          <ul className="ux-bp__slots">
            {sources.sitemap.map((slot) => (
              <li key={slot.epic_external_id} className="ux-bp__slot">
                <span className="ux-bp__slot-id">{slot.epic_external_id}</span>
                <span className="ux-bp__slot-label">{slot.label}</span>
                <code className="ux-bp__slot-route">{slot.route}</code>
                <Badge tone={slot.status === 'designed' ? 'success' : 'neutral'}>
                  {slot.status === 'designed' ? 'Designed' : 'Placeholder'}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <Banner tone="danger">{error}</Banner>}

      <div className="ux-bp__actions">
        <Button type="button" variant="primary" onClick={handleGenerate} disabled={working}>
          {busy === 'generate'
            ? exists
              ? 'Regenerating…'
              : 'Generating blueprint…'
            : exists
              ? 'Regenerate blueprint'
              : 'Generate platform blueprint'}
        </Button>
        <Button type="button" variant="secondary" onClick={handleSave} disabled={working}>
          {busy === 'save' ? 'Saving…' : 'Save brief'}
        </Button>
        {saved && <span className="ux-bp__saved">Saved</span>}
        <span className="ux-bp__hint">From requirements v{document.version}</span>
      </div>
    </section>
  )
}
