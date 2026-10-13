import { useState } from 'react'
import { api } from '../api/client'
import type { UxPrompt, UxPromptSources } from '../api/types'
import { UxBlueprintPanel } from '../components/UxBlueprintPanel'
import { UxFeaturePanel } from '../components/UxFeaturePanel'
import { UxPromptCard } from '../components/UxPromptCard'
import { Badge } from '../components/ui/Badge'
import { Banner } from '../components/ui/Banner'
import { Button, ButtonLink } from '../components/ui/Button'
import { Icon } from '../components/ui/Icon'
import { LockedState } from '../components/ui/LockedState'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { StepSegments } from '../components/ui/Progress'
import { isApproved } from '../lib/lifecycle'
import { plural } from '../lib/format'
import { projectHref } from '../lib/router'
import { useProject } from '../state/ProjectContext'
import { usePastedPrompts } from '../state/usePastedPrompts'
import { useUxPrompts } from '../state/useUxPrompts'
import './DesignPage.css'

const FIGMA_MAKE_URL = 'https://www.figma.com/make/'

const APPEARANCE_LABEL = { light: 'light', dark: 'dark', both: 'light and dark' } as const

const HEX_COLOR = /^#[0-9a-f]{3,8}$/i

function styleSummary(sources: UxPromptSources): { swatch: string | null; text: string } {
  const brief = sources.style_brief
  const color = brief.primary_color?.trim() ?? ''
  const swatch = HEX_COLOR.test(color) ? color : null
  const parts = [
    swatch ? null : brief.reference_brand || color,
    brief.tone,
    brief.appearance ? APPEARANCE_LABEL[brief.appearance] : null,
  ].filter(Boolean)
  const text = parts.join(' · ')
  return { swatch, text: text || (swatch ? swatch.toUpperCase() : 'Not set yet') }
}

interface StepRow {
  key: string
  title: string
  subtitle: string
  epicExternalId: string | null
  prompt: UxPrompt | undefined
  storyCount: number
}

export function DesignPage() {
  const { project, requirements, resources } = useProject()
  const approved = isApproved(requirements ?? null)

  if (requirements === undefined || resources === undefined) return <p className="page-status">Loading…</p>

  if (!approved) {
    const gaps = requirements?.unresolved_gap_count ?? 0
    const cta = !requirements
      ? { label: 'Add sources', href: projectHref(project.id, 'sources') }
      : gaps > 0
        ? { label: 'Resolve gaps now', href: projectHref(project.id, 'requirements', { tab: 'gaps' }) }
        : { label: 'Approve requirements', href: projectHref(project.id, 'requirements') }
    return (
      <LockedState
        icon="layout"
        title="Design prompts unlock after approval"
        body="Prompts are built from an approved version, so your stories can’t change underneath a design."
        checklist={[
          { label: 'Add sources', done: resources.length > 0 || Boolean(requirements) },
          { label: 'Generate requirements', done: Boolean(requirements) },
          { label: requirements && gaps > 0 ? `Fix ${plural(gaps, 'open gap')}` : 'Review the stories and fix any gaps', done: Boolean(requirements) && gaps === 0 },
          { label: 'Approve a version', done: false },
        ]}
        ctaLabel={cta.label}
        ctaHref={cta.href}
      />
    )
  }

  return <DesignPrompts />
}

function DesignPrompts() {
  const { project } = useProject()
  const { sources, prompts, error, loading, onBlueprint, onFeature, onChanged, onDeleted, refreshSources } = useUxPrompts(project.id)
  const { pasted, toggle, markPasted } = usePastedPrompts(project.id)
  const [openKey, setOpenKey] = useState<string | null>('blueprint')
  const [styleOpen, setStyleOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [generating, setGenerating] = useState<string | null>(null)
  const [genError, setGenError] = useState<string | null>(null)

  if (loading && !sources) return <p className="page-status">Loading…</p>

  if (error || !sources) {
    return (
      <div className="page">
        <Banner tone="danger">{error ?? 'Could not load design prompts'}</Banner>
      </div>
    )
  }

  if (!sources.document || sources.epics.length === 0) {
    return (
      <div className="page">
        <PageHeader title="Design prompts for Figma" />
        <Banner tone="warning">The approved version has no epics yet, so there is nothing to design. Add an epic on the Requirements page.</Banner>
      </div>
    )
  }

  const doc = sources.document
  const blueprint = prompts.find((p) => p.mode === 'foundation')
  const epicByExternalId = new Map(sources.epics.map((e) => [e.epic.external_id, e]))
  const latestFor = (externalId: string) =>
    prompts
      .filter((p) => p.mode !== 'foundation' && p.epic_external_id === externalId)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]

  const rows: StepRow[] = [
    {
      key: 'blueprint',
      title: 'Platform blueprint',
      subtitle: 'The look, navigation and layout shared by every screen. Paste this first.',
      epicExternalId: null,
      prompt: blueprint,
      storyCount: 0,
    },
    ...sources.suggested_order.flatMap((externalId): StepRow[] => {
      const entry = epicByExternalId.get(externalId)
      if (!entry) return []
      return [
        {
          key: externalId,
          title: entry.epic.text,
          subtitle: entry.stories
            .slice(0, 3)
            .map((s) => s.text)
            .join(' · '),
          epicExternalId: externalId,
          prompt: latestFor(externalId),
          storyCount: entry.stories.length,
        },
      ]
    }),
  ]

  const style = styleSummary(sources)
  const generated = rows.filter((r) => r.prompt)
  const pastedCount = generated.filter((r) => r.prompt && pasted.has(r.prompt.id)).length
  const canGenerateFeatures = sources.has_blueprint || sources.has_design_system

  async function generateFor(row: StepRow) {
    const entry = row.epicExternalId ? epicByExternalId.get(row.epicExternalId) : undefined
    if (!entry) return
    setGenerating(row.key)
    setGenError(null)
    try {
      const prompt = await api.generateUxPrompt(project.id, {
        documentId: doc.id,
        mode: 'new_feature',
        styleBrief: {},
        epicId: entry.epic.id,
        storyIds: entry.stories.map((s) => s.id),
      })
      onFeature(prompt)
      refreshSources()
    } catch (err) {
      setGenError(err instanceof Error ? err.message : 'Could not generate this prompt')
    } finally {
      setGenerating(null)
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="Design prompts for Figma"
        description={
          <>
            We turned your approved stories into a set of prompts. Paste them into Figma Make <strong>in order</strong> —
            the first one sets the look and layout, the rest add one feature at a time and stay consistent with it.
          </>
        }
        actions={
          <ButtonLink variant="primary" size="lg" icon="frame" href={FIGMA_MAKE_URL} target="_blank" rel="noreferrer">
            Open Figma Make
          </ButtonLink>
        }
      />

      <div className="design-strip">
        <div className="design-strip__progress">
          <p className="design-strip__label">Your progress</p>
          <p className="design-strip__value">
            {pastedCount} of {rows.length} {pastedCount === 1 ? 'prompt' : 'prompts'} pasted
          </p>
          <StepSegments
            label={`${pastedCount} of ${rows.length} prompts pasted`}
            states={rows.map((r) => (r.prompt && pasted.has(r.prompt.id) ? 'done' : 'upcoming'))}
          />
        </div>
        <div className="design-strip__style">
          {style.swatch ? <span className="design-strip__swatch" style={{ background: style.swatch }} aria-hidden="true" /> : <Icon name="shield" size={17} />}
          <span>
            <span className="design-strip__label">Style</span> {style.text}
          </span>
          <Button variant="secondary" size="sm" onClick={() => setStyleOpen((v) => !v)} aria-expanded={styleOpen}>
            {styleOpen ? 'Hide style' : 'Change style'}
          </Button>
        </div>
      </div>

      {(styleOpen || !blueprint) && (
        <UxBlueprintPanel
          key={`${doc.id}-${sources.blueprint_prompt_id ?? 'none'}`}
          projectId={project.id}
          sources={sources}
          onBlueprint={(prompt) => {
            onBlueprint(prompt)
            setOpenKey('blueprint')
          }}
        />
      )}

      {genError && <Banner tone="danger">{genError}</Banner>}

      <ol className="step-list">
        {rows.map((row, index) => {
          const open = openKey === row.key
          const isPasted = row.prompt ? pasted.has(row.prompt.id) : false
          return (
            <li key={row.key} className={`step-row ${open ? 'step-row--open' : ''}`}>
              <div className="step-row__head">
                <button
                  type="button"
                  className="step-row__toggle"
                  aria-expanded={open}
                  onClick={() => setOpenKey(open ? null : row.key)}
                >
                  <span className={`step-row__number ${isPasted ? 'step-row__number--done' : ''}`} aria-hidden="true">
                    {isPasted ? <Icon name="check" size={16} strokeWidth={2.5} /> : index + 1}
                  </span>
                  <span className="step-row__text">
                    <span className="step-row__title">{row.title}</span>
                    <span className="step-row__subtitle">{row.subtitle}</span>
                  </span>
                </button>

                <div className="step-row__chips">
                  {index === 0 && !isPasted && <Badge tone="accent">Start here</Badge>}
                  {row.storyCount > 0 && <Badge>{plural(row.storyCount, 'story', 'stories')}</Badge>}
                  {row.prompt?.is_stale && <Badge tone="warning" icon="alert">Outdated</Badge>}
                  {!row.prompt ? (
                    <Badge>Not generated</Badge>
                  ) : isPasted ? (
                    <Badge tone="success" icon="check">Pasted</Badge>
                  ) : (
                    <Badge>Not pasted yet</Badge>
                  )}
                  <Icon name={open ? 'chevron-up' : 'chevron-down'} size={18} className="step-row__chevron" />
                </div>
              </div>

              {open && (
                <div className="step-row__body">
                  {row.prompt ? (
                    <>
                      <UxPromptCard
                        key={`${row.prompt.id}-${row.prompt.updated_at}`}
                        projectId={project.id}
                        prompt={row.prompt}
                        embedded
                        onChanged={onChanged}
                        onDeleted={onDeleted}
                        onCopied={() => row.prompt && markPasted(row.prompt.id)}
                      />
                      <label className="step-row__pasted">
                        <input type="checkbox" checked={isPasted} onChange={() => row.prompt && toggle(row.prompt.id)} />
                        I’ve pasted this into Figma Make
                      </label>
                    </>
                  ) : row.epicExternalId ? (
                    <div className="step-row__empty">
                      <p>
                        {canGenerateFeatures
                          ? 'This feature has no prompt yet. Generate one that fits into the platform blueprint.'
                          : 'Set up the platform blueprint first — every feature is built to fit it.'}
                      </p>
                      <Button
                        variant="primary"
                        icon="sparkles"
                        loading={generating === row.key}
                        disabled={!canGenerateFeatures || generating !== null}
                        onClick={() => generateFor(row)}
                      >
                        Generate this prompt
                      </Button>
                    </div>
                  ) : (
                    <div className="step-row__empty">
                      <p>The blueprint isn’t generated yet. Set the style above, then generate it.</p>
                      <Button variant="primary" icon="sparkles" onClick={() => setStyleOpen(true)}>
                        Set up the blueprint
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ol>

      <Panel
        title="More ways to generate"
        description="Create several prompts at once, change the order, or design an edit to screens that already exist."
        tone="sunken"
        actions={
          <Button variant="secondary" size="sm" onClick={() => setMoreOpen((v) => !v)} aria-expanded={moreOpen}>
            {moreOpen ? 'Hide' : 'Show'}
          </Button>
        }
      >
        {moreOpen && <UxFeaturePanel key={doc.id} projectId={project.id} sources={sources} onPrompt={onFeature} onFinished={refreshSources} />}
      </Panel>

      <aside className="design-next">
        <Icon name="help" size={20} />
        <p>
          Done designing? Export your screens from Figma as PDF or image, then use <strong>Validate design</strong> to
          check them against your requirements.
        </p>
        <ButtonLink variant="secondary" href={projectHref(project.id, 'validate')} iconAfter="arrow-right">
          Go to Validate design
        </ButtonLink>
      </aside>
    </div>
  )
}
