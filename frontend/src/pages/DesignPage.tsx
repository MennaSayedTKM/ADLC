import { useState } from 'react'
import { api } from '../api/client'
import type { EpicWithStories, RequirementItem, UxPrompt, UxPromptSources } from '../api/types'
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
  /** Oldest first; an epic can have several prompts, each covering some of its stories. */
  prompts: UxPrompt[]
  stories: RequirementItem[]
}

/** Stories of an epic that some prompt already covers. */
function coveredStoryIds(prompts: UxPrompt[]): Set<string> {
  return new Set(prompts.flatMap((p) => p.story_ids))
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

/** Tick the stories a prompt should cover. Everything is ticked by default. */
function StoryPicker({
  stories,
  excluded,
  disabled,
  onToggle,
  onSetAll,
}: {
  stories: RequirementItem[]
  excluded: Set<string>
  disabled: boolean
  onToggle: (storyId: string) => void
  onSetAll: (stories: RequirementItem[], selected: boolean) => void
}) {
  const chosen = stories.filter((s) => !excluded.has(s.id)).length
  return (
    <fieldset className="story-picker" disabled={disabled}>
      <legend className="story-picker__legend">
        Stories to cover <span>· {chosen} of {stories.length}</span>
      </legend>
      <div className="story-picker__bulk">
        <button type="button" className="link-button" onClick={() => onSetAll(stories, true)}>
          Select all
        </button>
        <button type="button" className="link-button" onClick={() => onSetAll(stories, false)}>
          Select none
        </button>
      </div>
      <ul className="story-picker__list">
        {stories.map((story) => (
          <li key={story.id}>
            <label className="story-picker__item">
              <input type="checkbox" checked={!excluded.has(story.id)} onChange={() => onToggle(story.id)} />
              <span className="story-picker__id">{story.external_id}</span>
              <span>{story.text}</span>
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  )
}

function DesignPrompts() {
  const { project } = useProject()
  const { sources, prompts, error, loading, onBlueprint, onFeature, onChanged, onDeleted, refreshSources } = useUxPrompts(project.id)
  const { pasted, toggle, markPasted } = usePastedPrompts(project.id)
  const [openKey, setOpenKey] = useState<string | null>('blueprint')
  const [styleOpen, setStyleOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [generating, setGenerating] = useState<string | null>(null)
  const [bulk, setBulk] = useState<{ done: number; total: number } | null>(null)
  const [genError, setGenError] = useState<string | null>(null)
  // Epics ticked for "generate several at once", and stories the person unticked.
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [excluded, setExcluded] = useState<Set<string>>(new Set())

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
  const epicByExternalId = new Map<string, EpicWithStories>(sources.epics.map((e) => [e.epic.external_id, e]))
  const promptsFor = (externalId: string) =>
    prompts
      .filter((p) => p.mode !== 'foundation' && p.epic_external_id === externalId)
      .sort((a, b) => a.created_at.localeCompare(b.created_at))

  const rows: StepRow[] = [
    {
      key: 'blueprint',
      title: 'Platform blueprint',
      subtitle: 'The look, navigation and layout shared by every screen. Paste this first.',
      epicExternalId: null,
      prompts: blueprint ? [blueprint] : [],
      stories: [],
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
          prompts: promptsFor(externalId),
          stories: entry.stories,
        },
      ]
    }),
  ]

  const style = styleSummary(sources)
  const canGenerateFeatures = sources.has_blueprint || sources.has_design_system
  const busy = generating !== null || bulk !== null

  // One progress unit per prompt, plus one for every row that has none yet.
  const units = rows.flatMap((r) => (r.prompts.length > 0 ? r.prompts.map((p) => pasted.has(p.id)) : [false]))
  const pastedCount = units.filter(Boolean).length

  function toggleStory(storyId: string) {
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(storyId)) next.delete(storyId)
      else next.add(storyId)
      return next
    })
  }

  function setStories(stories: RequirementItem[], selected: boolean) {
    setExcluded((prev) => {
      const next = new Set(prev)
      for (const s of stories) {
        if (selected) next.delete(s.id)
        else next.add(s.id)
      }
      return next
    })
  }

  function togglePicked(key: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  /** The stories a new prompt for this row would cover: ticked, and not covered by an earlier prompt. */
  function pendingStories(row: StepRow): RequirementItem[] {
    const covered = coveredStoryIds(row.prompts)
    return row.stories.filter((s) => !covered.has(s.id) && !excluded.has(s.id))
  }

  async function generateOne(row: StepRow, stories: RequirementItem[]) {
    const entry = row.epicExternalId ? epicByExternalId.get(row.epicExternalId) : undefined
    if (!entry || stories.length === 0) return
    const prompt = await api.generateUxPrompt(project.id, {
      documentId: doc.id,
      mode: 'new_feature',
      styleBrief: {},
      epicId: entry.epic.id,
      storyIds: stories.map((s) => s.id),
    })
    onFeature(prompt)
  }

  async function generateFor(row: StepRow) {
    setGenerating(row.key)
    setGenError(null)
    try {
      await generateOne(row, pendingStories(row))
      refreshSources()
    } catch (err) {
      setGenError(err instanceof Error ? err.message : 'Could not generate this prompt')
    } finally {
      setGenerating(null)
    }
  }

  // One request per epic, in the order shown: each prompt is generated knowing the screens the
  // previous ones created. A failure doesn't stop the rest.
  async function generateSelected() {
    const chosen = rows.filter((r) => r.epicExternalId && picked.has(r.key) && pendingStories(r).length > 0)
    if (chosen.length === 0) return
    setBulk({ done: 0, total: chosen.length })
    setGenError(null)
    const failed: string[] = []
    for (const row of chosen) {
      try {
        await generateOne(row, pendingStories(row))
      } catch (err) {
        failed.push(`${row.title}: ${err instanceof Error ? err.message : 'could not be generated'}`)
      }
      setBulk((prev) => (prev ? { ...prev, done: prev.done + 1 } : prev))
    }
    setBulk(null)
    setPicked(new Set())
    refreshSources()
    if (failed.length > 0) setGenError(failed.join(' · '))
  }

  const pickableRows = rows.filter((r) => r.epicExternalId)
  const readyToPick = pickableRows.filter((r) => pendingStories(r).length > 0)
  const selectedCount = readyToPick.filter((r) => picked.has(r.key)).length

  return (
    <div className="page">
      <PageHeader
        title="Design prompts for Figma"
        description={
          <>
            We turned your approved stories into a set of prompts. Paste them into Figma Make <strong>in order</strong> —
            the first one sets the look and layout, the rest add one feature at a time and stay consistent with it.
            Generate a prompt for a whole epic, or tick just the stories you want.
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
            {pastedCount} of {units.length} {units.length === 1 ? 'prompt' : 'prompts'} pasted
          </p>
          <StepSegments
            label={`${pastedCount} of ${units.length} prompts pasted`}
            states={units.map((done) => (done ? 'done' : 'upcoming'))}
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

      <div className="bulk-bar" role="group" aria-label="Generate several prompts at once">
        <label className="bulk-bar__all">
          <input
            type="checkbox"
            checked={readyToPick.length > 0 && selectedCount === readyToPick.length}
            disabled={!canGenerateFeatures || busy || readyToPick.length === 0}
            onChange={(e) => setPicked(e.target.checked ? new Set(readyToPick.map((r) => r.key)) : new Set())}
          />
          Select every epic that still needs a prompt
        </label>
        <span className="bulk-bar__count">{selectedCount > 0 ? `${plural(selectedCount, 'epic')} selected` : 'Tick epics below to generate them together'}</span>
        <Button
          variant="primary"
          icon="sparkles"
          loading={bulk !== null}
          disabled={selectedCount === 0 || busy || !canGenerateFeatures}
          onClick={generateSelected}
        >
          {bulk ? `Generating ${Math.min(bulk.done + 1, bulk.total)} of ${bulk.total}…` : selectedCount > 1 ? `Generate ${selectedCount} prompts` : 'Generate prompt'}
        </Button>
      </div>
      {!canGenerateFeatures && (
        <p className="bulk-note">Set up the platform blueprint first — every feature is built to fit it.</p>
      )}

      <ol className="step-list">
        {rows.map((row, index) => {
          const open = openKey === row.key
          const isEpic = row.epicExternalId !== null
          const allPasted = row.prompts.length > 0 && row.prompts.every((p) => pasted.has(p.id))
          const covered = coveredStoryIds(row.prompts)
          const uncovered = row.stories.filter((s) => !covered.has(s.id))
          const pending = pendingStories(row)
          const rowBusy = generating === row.key
          return (
            <li key={row.key} className={`step-row ${open ? 'step-row--open' : ''}`}>
              <div className="step-row__head">
                {isEpic && (
                  <input
                    type="checkbox"
                    className="step-row__pick"
                    checked={picked.has(row.key) && uncovered.length > 0}
                    disabled={!canGenerateFeatures || busy || uncovered.length === 0}
                    onChange={() => togglePicked(row.key)}
                    aria-label={uncovered.length === 0 ? `${row.title} is fully covered` : `Include ${row.title} in the batch`}
                  />
                )}
                <button
                  type="button"
                  className="step-row__toggle"
                  aria-expanded={open}
                  onClick={() => setOpenKey(open ? null : row.key)}
                >
                  <span className={`step-row__number ${allPasted ? 'step-row__number--done' : ''}`} aria-hidden="true">
                    {allPasted ? <Icon name="check" size={16} strokeWidth={2.5} /> : index + 1}
                  </span>
                  <span className="step-row__text">
                    <span className="step-row__title">{row.title}</span>
                    <span className="step-row__subtitle">{row.subtitle}</span>
                  </span>
                </button>

                <div className="step-row__chips">
                  {index === 0 && !allPasted && <Badge tone="accent">Start here</Badge>}
                  {isEpic && (
                    <Badge tone={row.prompts.length > 0 && uncovered.length === 0 ? 'success' : 'neutral'}>
                      {row.prompts.length === 0
                        ? plural(row.stories.length, 'story', 'stories')
                        : uncovered.length === 0
                          ? `All ${row.stories.length} stories covered`
                          : `${row.stories.length - uncovered.length} of ${row.stories.length} stories covered`}
                    </Badge>
                  )}
                  {row.prompts.some((p) => p.is_stale) && <Badge tone="warning" icon="alert">Outdated</Badge>}
                  {row.prompts.length === 0 ? (
                    <Badge>Not generated</Badge>
                  ) : allPasted ? (
                    <Badge tone="success" icon="check">Pasted</Badge>
                  ) : (
                    <Badge>Not pasted yet</Badge>
                  )}
                  <Icon name={open ? 'chevron-up' : 'chevron-down'} size={18} className="step-row__chevron" />
                </div>
              </div>

              {open && (
                <div className="step-row__body">
                  {row.prompts.map((prompt, n) => (
                    <div key={prompt.id} className="step-row__prompt">
                      {row.prompts.length > 1 && <p className="step-row__prompt-title">Prompt {n + 1} of {row.prompts.length}</p>}
                      <UxPromptCard
                        key={`${prompt.id}-${prompt.updated_at}`}
                        projectId={project.id}
                        prompt={prompt}
                        embedded
                        onChanged={onChanged}
                        onDeleted={onDeleted}
                        onCopied={() => markPasted(prompt.id)}
                      />
                      <label className="step-row__pasted">
                        <input type="checkbox" checked={pasted.has(prompt.id)} onChange={() => toggle(prompt.id)} />
                        I’ve pasted this into Figma Make
                      </label>
                    </div>
                  ))}

                  {isEpic && uncovered.length > 0 && (
                    <div className="step-row__generate">
                      <p>
                        {row.prompts.length === 0
                          ? canGenerateFeatures
                            ? 'No prompt yet. Choose which stories it should cover — all of them make one prompt for the whole epic.'
                            : 'Set up the platform blueprint first — every feature is built to fit it.'
                          : `${plural(uncovered.length, 'story', 'stories')} not covered by an earlier prompt. Generate another prompt for them.`}
                      </p>
                      <StoryPicker stories={uncovered} excluded={excluded} disabled={rowBusy} onToggle={toggleStory} onSetAll={setStories} />
                      <div className="step-row__generate-actions">
                        <Button
                          variant="primary"
                          icon="sparkles"
                          loading={rowBusy}
                          disabled={!canGenerateFeatures || busy || pending.length === 0}
                          onClick={() => generateFor(row)}
                        >
                          {pending.length === uncovered.length && row.prompts.length === 0
                            ? 'Generate prompt for the whole epic'
                            : `Generate prompt for ${plural(pending.length, 'story', 'stories')}`}
                        </Button>
                        {pending.length === 0 && <span className="step-row__hint">Tick at least one story.</span>}
                      </div>
                    </div>
                  )}

                  {!isEpic && row.prompts.length === 0 && (
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
        description="Change the order of epics, or design an edit to screens that already exist."
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
