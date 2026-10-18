import { useState } from 'react'
import { api } from '../../api/client'
import type { JiraEpicPreview, JiraPreviewData } from '../../api/types'
import { plural, relativeTime } from '../../lib/format'
import { projectHref } from '../../lib/router'
import { Badge } from '../ui/Badge'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import { Modal } from '../ui/Modal'
import { Panel } from '../ui/Panel'
import './JiraSendPanel.css'

interface Props {
  projectId: string
  preview: JiraPreviewData | null
  loading: boolean
  error: string | null
  onChanged: (preview: JiraPreviewData) => void
  refresh: () => Promise<void>
}

type Outcome = { created: number; updated: number; attachments: number; error: string | null }

/** Sends the chosen epics' development stories to Jira, one epic per request, after a confirmation. */
export function JiraSendPanel({ projectId, preview, loading, error, onChanged, refresh }: Props) {
  const [excluded, setExcluded] = useState<Set<string>>(new Set())
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [sending, setSending] = useState<{ current: string; done: number; total: number } | null>(null)
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({})

  if (loading && !preview) return <p className="page-status">Loading…</p>
  if (error || !preview) return <Banner tone="danger">{error ?? 'Could not load the Jira preview'}</Banner>

  const devStoriesHref = projectHref(projectId, 'dev-stories')
  const settings = preview.settings
  if (!settings) {
    return (
      <Panel title="Jira" description="Development stories are sent to the Jira project connected on the Dev stories page.">
        <Banner tone="info" action={<a className="btn btn--secondary btn--sm" href={devStoriesHref}>Go to Dev stories</a>}>
          Connect a Jira project first: enter its key (e.g. TK) in the <strong>Jira project</strong> panel on Dev stories.
        </Banner>
      </Panel>
    )
  }
  if (preview.epics.length === 0) {
    return (
      <Panel title="Jira" description={`Sending to ${settings.project_key} · ${settings.project_name}.`}>
        <Banner tone="info" action={<a className="btn btn--secondary btn--sm" href={devStoriesHref}>Plan development stories</a>}>
          No development stories are planned yet. Plan them on Dev stories, then send them here.
        </Banner>
      </Panel>
    )
  }

  const chosen = preview.epics.filter((e) => !excluded.has(e.external_id))
  const sum = (epics: JiraEpicPreview[], key: keyof JiraEpicPreview) => epics.reduce((n, e) => n + (e[key] as number), 0)
  const withoutPrompt = sum(preview.epics, 'tasks_without_prompt')
  const stale = sum(preview.epics, 'stale_stories')
  const issues = sum(chosen, 'stories') + sum(chosen, 'tasks')
  const newIssues = sum(chosen, 'new_stories') + sum(chosen, 'new_tasks')
  const newOrUpdated =
    newIssues === issues ? 'all new' : newIssues === 0 ? 'all updated' : `${newIssues} new, ${issues - newIssues} updated`

  function toggle(id: string) {
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function send() {
    setConfirmOpen(false)
    const epics = chosen
    let current = preview!
    for (const [i, epic] of epics.entries()) {
      setSending({ current: epic.external_id, done: i, total: epics.length })
      try {
        const result = await api.sendEpicToJira(projectId, epic.external_id)
        setOutcomes((prev) => ({ ...prev, [epic.external_id]: result }))
        if (result.epic) {
          current = { ...current, epics: current.epics.map((e) => (e.external_id === epic.external_id ? result.epic! : e)) }
          onChanged(current)
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Could not send this epic'
        setOutcomes((prev) => ({ ...prev, [epic.external_id]: { created: 0, updated: 0, attachments: 0, error: message } }))
      }
    }
    setSending(null)
    await refresh()
  }

  return (
    <Panel
      title="Send to Jira"
      description={
        <>
          To <strong>{settings.project_key}</strong> · {settings.project_name}.{' '}
          <a href={devStoriesHref}>Change the project or the stories on Dev stories</a>.
        </>
      }
    >
      {withoutPrompt > 0 && (
        <Banner tone="warning">
          {plural(withoutPrompt, 'technical task')} {withoutPrompt === 1 ? 'has' : 'have'} no coding prompt yet. {withoutPrompt === 1 ? 'It is' : 'They are'} sent
          with {withoutPrompt === 1 ? 'its' : 'their'} summary; write the prompts on Dev stories and send again to fill them in.
        </Banner>
      )}
      {stale > 0 && (
        <Banner tone="warning">
          {plural(stale, 'development story', 'development stories')} {stale === 1 ? 'was' : 'were'} planned from an older
          requirements version. Plan those epics again on Dev stories if the stories changed.
        </Banner>
      )}
      {preview.design.unlinked_screens > 0 && (
        <Banner tone="info">
          {plural(preview.design.unlinked_screens, 'screen')} from the last design check{' '}
          {preview.design.unlinked_screens === 1 ? 'isn’t' : 'aren’t'} linked to a user story (the check ran before links
          were kept), so {preview.design.unlinked_screens === 1 ? 'it' : 'they'} can’t be attached. Upload the screens again
          on <a href={projectHref(projectId, 'validate')}>Validate design</a> to link them.
        </Banner>
      )}

      <div className="jira-send__toolbar">
        <span className="jira-send__count">
          {chosen.length} of {plural(preview.epics.length, 'planned epic')} selected
          {preview.unplanned_epics > 0 && ` · ${plural(preview.unplanned_epics, 'epic')} not planned yet`}
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={sending !== null}
          onClick={() => setExcluded(chosen.length === preview.epics.length ? new Set(preview.epics.map((e) => e.external_id)) : new Set())}
        >
          {chosen.length === preview.epics.length ? 'Select none' : 'Select all'}
        </Button>
      </div>

      <ul className="jira-send__epics">
        {preview.epics.map((epic) => {
          const outcome = outcomes[epic.external_id]
          const checkboxId = `jira-epic-${epic.external_id}`
          return (
            <li key={epic.external_id} className="jira-send__epic">
              <input
                id={checkboxId}
                type="checkbox"
                checked={!excluded.has(epic.external_id)}
                onChange={() => toggle(epic.external_id)}
                disabled={sending !== null}
              />
              <div className="jira-send__epic-text">
                <label htmlFor={checkboxId} className="jira-send__epic-title">
                  <span className="jira-send__epic-id">{epic.external_id}</span> {epic.title}
                </label>
                <p className="jira-send__epic-meta">
                  {plural(epic.stories, 'story', 'stories')}
                  {epic.jira_key && epic.new_stories > 0 && ` (${epic.new_stories} new)`} ·{' '}
                  {plural(epic.tasks, 'sub-task')}
                  {epic.jira_key && epic.new_tasks > 0 && ` (${epic.new_tasks} new)`}
                  {epic.screens_to_attach > 0 && ` · ${plural(epic.screens_to_attach, 'screen')} to attach`}
                  {epic.synced_at && ` · last sent ${relativeTime(epic.synced_at)}`}
                </p>
                {outcome && (
                  outcome.error ? (
                    <Banner tone="danger">{outcome.error}</Banner>
                  ) : (
                    <p className="jira-send__outcome">
                      <Icon name="check" size={15} /> Sent: {outcome.created} created, {outcome.updated} updated
                      {outcome.attachments > 0 && `, ${plural(outcome.attachments, 'attachment')}`}
                    </p>
                  )
                )}
              </div>
              <div className="jira-send__epic-badges">
                {epic.tasks_without_prompt > 0 && <Badge tone="warning" icon="alert">{epic.tasks_without_prompt} without prompt</Badge>}
                {sending?.current === epic.external_id && <Badge tone="info" icon="refresh">Sending…</Badge>}
                {epic.jira_key ? (
                  <a className="jira-send__key" href={epic.jira_url ?? undefined} target="_blank" rel="noreferrer">
                    {epic.jira_key} <Icon name="external" size={14} />
                  </a>
                ) : (
                  <Badge>Not sent</Badge>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      <div className="publish-actions">
        <Button variant="primary" size="lg" icon="send" disabled={chosen.length === 0} loading={sending !== null} onClick={() => setConfirmOpen(true)}>
          {sending
            ? `Sending ${sending.current} (${sending.done + 1} of ${sending.total})…`
            : `Send ${plural(chosen.length, 'epic')} to Jira`}
        </Button>
      </div>

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={`Send ${plural(chosen.length, 'epic')} to ${settings.project_key}?`}
        description="This creates or updates issues in Jira that your team can see."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" icon="send" onClick={send}>
              Send now
            </Button>
          </>
        }
      >
        <ul className="publish-facts">
          <li>
            <Icon name="check" size={16} /> {plural(sum(chosen, 'stories'), 'story', 'stories')} and {plural(sum(chosen, 'tasks'), 'sub-task')}
            {' '}({newOrUpdated}), plus each epic
          </li>
          <li>
            <Icon name="check" size={16} /> {plural(sum(chosen, 'screens_to_attach'), 'screen')} attached to frontend sub-tasks
          </li>
          <li>
            <Icon name="check" size={16} /> Nothing is deleted in Jira; changes people made to labels there are kept
          </li>
        </ul>
      </Modal>
    </Panel>
  )
}
