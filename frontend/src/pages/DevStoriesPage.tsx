import { useState } from 'react'
import { api } from '../api/client'
import type { DevEpic, DevStory, DevTask } from '../api/types'
import { DevTaskRow } from '../components/dev/DevTaskRow'
import { JiraProjectPanel } from '../components/dev/JiraProjectPanel'
import { TechStackPanel } from '../components/dev/TechStackPanel'
import { Badge } from '../components/ui/Badge'
import { Banner } from '../components/ui/Banner'
import { Button } from '../components/ui/Button'
import { Icon } from '../components/ui/Icon'
import { LockedState } from '../components/ui/LockedState'
import { PageHeader } from '../components/ui/PageHeader'
import { plural } from '../lib/format'
import { isApproved } from '../lib/lifecycle'
import { projectHref } from '../lib/router'
import { useDevStories } from '../state/useDevStories'
import { useJiraPreview } from '../state/useJiraPreview'
import { useProject } from '../state/ProjectContext'
import './DevStoriesPage.css'

/** Approved user stories -> development stories (Jira Stories) -> technical tasks (Sub-tasks) with coding prompts. */
export function DevStoriesPage() {
  const { project, requirements } = useProject()

  if (requirements === undefined) return <p className="page-status">Loading…</p>
  if (!isApproved(requirements)) {
    return (
      <LockedState
        icon="branch"
        title="Development stories unlock after approval"
        body="Development stories and coding prompts are planned from an approved version, so the stories can’t change underneath the team."
        checklist={[
          { label: 'Generate requirements', done: Boolean(requirements) },
          { label: 'Review the stories and fix any gaps', done: Boolean(requirements) && requirements?.unresolved_gap_count === 0 },
          { label: 'Approve a version', done: false },
        ]}
        ctaLabel={requirements ? 'Approve requirements' : 'Add sources'}
        ctaHref={projectHref(project.id, requirements ? 'requirements' : 'sources')}
      />
    )
  }
  return <DevStories />
}

function DevStories() {
  const { project } = useProject()
  const { overview, error, loading, refresh, replaceEpicStories, replaceStory, replaceTask } = useDevStories(project.id)
  const jira = useJiraPreview(project.id)
  const [openEpic, setOpenEpic] = useState<string | null>(null)
  const [planning, setPlanning] = useState<{ current: string; done: number; total: number } | null>(null)
  const [writing, setWriting] = useState<{ taskId: string; done: number; total: number } | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  // Shown on the task itself, where the user clicked; a batch also gets a summary at the top.
  const [taskErrors, setTaskErrors] = useState<Record<string, string>>({})

  if (loading && !overview) return <p className="page-status">Loading…</p>
  if (error || !overview) {
    return (
      <div className="page">
        <Banner tone="danger">{error ?? 'Could not load development stories'}</Banner>
      </div>
    )
  }

  const busy = planning !== null || writing !== null
  const unplanned = overview.epics.filter((e) => e.dev_stories.length === 0)

  async function plan(epics: DevEpic[]) {
    const failed: string[] = []
    setActionError(null)
    for (const [i, epic] of epics.entries()) {
      setPlanning({ current: epic.external_id, done: i, total: epics.length })
      try {
        replaceEpicStories(epic.external_id, await api.generateDevStories(project.id, epic.external_id))
        setOpenEpic(epic.external_id)
      } catch (err) {
        failed.push(`${epic.external_id}: ${err instanceof Error ? err.message : 'could not be planned'}`)
      }
    }
    setPlanning(null)
    if (failed.length > 0) setActionError(failed.join(' · '))
  }

  function replan(epic: DevEpic) {
    if (
      epic.dev_stories.length > 0 &&
      !window.confirm(`Plan ${epic.external_id} again? Its development stories, tasks and coding prompts are replaced.`)
    )
      return
    plan([epic])
  }

  // One request per task, in order, so a long batch never runs as one request and a failure doesn't stop the rest.
  async function writePrompts(tasks: DevTask[]) {
    let failed = 0
    setActionError(null)
    for (const [i, task] of tasks.entries()) {
      setWriting({ taskId: task.id, done: i, total: tasks.length })
      let message: string | null = null
      try {
        replaceTask(await api.writeCodingPrompt(project.id, task.id))
      } catch (err) {
        message = err instanceof Error ? err.message : 'The coding prompt could not be written'
        failed += 1
      }
      setTaskErrors((prev) => {
        const next = { ...prev }
        if (message) next[task.id] = message
        else delete next[task.id]
        return next
      })
    }
    setWriting(null)
    if (tasks.length > 1 && failed > 0) {
      setActionError(`${failed} of ${tasks.length} coding prompts could not be written. The reason is shown on each task.`)
    }
  }

  function removeStory(story: DevStory) {
    if (!window.confirm(`Delete the development story “${story.title}” and its tasks? This cannot be undone.`)) return
    api
      .deleteDevStory(project.id, story.id)
      .then(() => {
        const epic = overview!.epics.find((e) => e.external_id === story.epic_external_id)
        if (epic) replaceEpicStories(epic.external_id, epic.dev_stories.filter((s) => s.id !== story.id))
      })
      .catch((err) => setActionError(err instanceof Error ? err.message : 'Could not delete the story'))
  }

  function removeTask(story: DevStory, taskId: string) {
    replaceStory({ ...story, tasks: story.tasks.filter((t) => t.id !== taskId) })
  }

  return (
    <div className="page">
      <PageHeader
        title="Dev stories"
        description={
          <>
            Turn the approved user stories into work for the development team: each user story becomes one or more
            development stories (Jira Stories) under its epic, and each of those gets technical tasks (Sub-tasks) with a
            detailed coding prompt. Send them to Jira from Publish &amp; export when they’re ready.
          </>
        }
      />

      <TechStackPanel key={overview.tech_profile.document_name ?? 'none'} projectId={project.id} profile={overview.tech_profile} onSaved={refresh} />

      <JiraProjectPanel
        key={`jira-${jira.preview?.settings?.project_key ?? 'none'}`}
        projectId={project.id}
        preview={jira.preview}
        onConnected={jira.setPreview}
      />

      {actionError && <Banner tone="danger">{actionError}</Banner>}

      <div className="dev-bar" role="group" aria-label="Plan development stories">
        <p className="dev-bar__text">
          {planning
            ? `Planning ${planning.current} (${planning.done + 1} of ${planning.total})…`
            : writing
              ? `Writing coding prompt ${writing.done + 1} of ${writing.total}…`
              : unplanned.length > 0
                ? `${plural(unplanned.length, 'epic')} not planned yet. Epics are listed in dependency order.`
                : 'Every epic is planned. Epics are listed in dependency order.'}
        </p>
        {unplanned.length > 0 && (
          <Button variant="primary" icon="sparkles" loading={planning !== null} disabled={busy} onClick={() => plan(unplanned)}>
            {unplanned.length === overview.epics.length ? 'Plan every epic' : `Plan ${plural(unplanned.length, 'remaining epic')}`}
          </Button>
        )}
      </div>

      <ol className="dev-epics">
        {overview.epics.map((epic) => {
          const open = openEpic === epic.external_id
          const tasks = epic.dev_stories.flatMap((s) => s.tasks)
          const withoutPrompt = tasks.filter((t) => t.coding_prompt === null)
          const decisions = tasks.filter((t) => t.tech_decision_needed).length
          return (
            <li key={epic.external_id} className={`dev-epic ${open ? 'dev-epic--open' : ''}`}>
              <div className="dev-epic__head">
                <button type="button" className="dev-epic__toggle" aria-expanded={open} onClick={() => setOpenEpic(open ? null : epic.external_id)}>
                  <span className="dev-epic__id">{epic.external_id}</span>
                  <span className="dev-epic__title">{epic.title}</span>
                  <span className="dev-epic__meta">
                    {plural(epic.stories.length, 'user story', 'user stories')}
                    {epic.dev_stories.length > 0 &&
                      ` · ${plural(epic.dev_stories.length, 'development story', 'development stories')} · ${plural(tasks.length, 'task')}`}
                  </span>
                </button>
                <div className="dev-epic__badges">
                  {epic.dev_stories.length === 0 ? (
                    <Badge>Not planned</Badge>
                  ) : withoutPrompt.length === 0 ? (
                    <Badge tone="success" icon="check">All prompts written</Badge>
                  ) : (
                    <Badge>{`${tasks.length - withoutPrompt.length} of ${tasks.length} prompts written`}</Badge>
                  )}
                  {decisions > 0 && <Badge tone="warning" icon="alert">{plural(decisions, 'decision')} needed</Badge>}
                  {epic.dev_stories.some((s) => s.is_stale) && <Badge tone="warning" icon="alert">From an older version</Badge>}
                  <Icon name={open ? 'chevron-up' : 'chevron-down'} size={18} className="dev-epic__chevron" />
                </div>
              </div>

              {open && (
                <div className="dev-epic__body">
                  <div className="dev-epic__actions">
                    <Button
                      variant={epic.dev_stories.length === 0 ? 'primary' : 'secondary'}
                      size="sm"
                      icon="sparkles"
                      loading={planning?.current === epic.external_id}
                      disabled={busy}
                      onClick={() => replan(epic)}
                    >
                      {epic.dev_stories.length === 0 ? 'Plan development stories' : 'Plan again'}
                    </Button>
                    {withoutPrompt.length > 0 && (
                      <Button variant="primary" size="sm" icon="sparkles" disabled={busy} onClick={() => writePrompts(withoutPrompt)}>
                        Write {plural(withoutPrompt.length, 'coding prompt')}
                      </Button>
                    )}
                  </div>

                  {epic.dev_stories.length === 0 && (
                    <p className="dev-epic__empty">
                      Not planned yet. Planning reads this epic’s approved user stories:{' '}
                      {epic.stories.map((s) => s.external_id).join(', ') || 'none'}.
                    </p>
                  )}

                  {epic.dev_stories.map((story) => (
                    <article key={story.id} className="dev-story">
                      <header className="dev-story__head">
                        <div>
                          <h3 className="dev-story__title">{story.title}</h3>
                          <p className="dev-story__meta">
                            {story.source_story_external_id && <>From {story.source_story_external_id}</>}
                            {story.story_points !== null && <> · {plural(story.story_points, 'point')}</>}
                            {story.jira_key && (
                              <>
                                {' · '}
                                <a href={story.jira_url ?? undefined} target="_blank" rel="noreferrer" className="dev-story__jira">
                                  {story.jira_key} <Icon name="external" size={13} />
                                </a>
                              </>
                            )}
                          </p>
                        </div>
                        <div className="dev-story__badges">
                          {story.labels.map((label) => (
                            <Badge key={label} tone="info">{label}</Badge>
                          ))}
                          {story.is_stale && <Badge tone="warning" icon="alert">Older version</Badge>}
                          <Button variant="ghost" size="sm" icon="trash" disabled={busy} onClick={() => removeStory(story)} aria-label={`Delete development story ${story.title}`}>
                            Delete
                          </Button>
                        </div>
                      </header>
                      <StoryDescription text={story.description} />
                      {story.acceptance_criteria.length > 0 && (
                        <>
                          <p className="dev-story__label">Acceptance criteria</p>
                          <ul className="dev-story__criteria">
                            {story.acceptance_criteria.map((c, i) => (
                              <li key={i}>{c}</li>
                            ))}
                          </ul>
                        </>
                      )}
                      <p className="dev-story__label">Technical tasks</p>
                      <ul className="dev-story__tasks">
                        {story.tasks.map((task) => (
                          <DevTaskRow
                            key={task.id}
                            projectId={project.id}
                            task={task}
                            writing={writing?.taskId === task.id}
                            writeError={taskErrors[task.id] ?? null}
                            disabled={busy}
                            onWrite={(t) => writePrompts([t])}
                            onChanged={replaceTask}
                            onDeleted={(id) => removeTask(story, id)}
                          />
                        ))}
                      </ul>
                    </article>
                  ))}
                </div>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

/** The description is the Jira text: paragraphs, "**Label**" headings and "- " bullet lists. Shown as such, not as raw markdown. */
function StoryDescription({ text }: { text: string }) {
  return (
    <div className="dev-story__description">
      {text.split(/\n\s*\n/).map((block, i) => {
        const lines = block.split('\n').filter((l) => l.trim())
        const heading = lines[0]?.match(/^\*\*(.+)\*\*$/)
        const body = heading ? lines.slice(1) : lines
        const bullets = body.length > 0 && body.every((l) => /^\s*[-*] /.test(l))
        return (
          <div key={i}>
            {heading && <p className="dev-story__label">{heading[1]}</p>}
            {bullets ? (
              <ul className="dev-story__criteria">
                {body.map((l, j) => (
                  <li key={j}>{l.replace(/^\s*[-*] /, '')}</li>
                ))}
              </ul>
            ) : (
              body.length > 0 && <p>{body.join('\n')}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}
