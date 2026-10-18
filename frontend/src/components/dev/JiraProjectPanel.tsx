import { useId, useState } from 'react'
import { api } from '../../api/client'
import type { JiraPreviewData } from '../../api/types'
import { projectHref } from '../../lib/router'
import { Badge } from '../ui/Badge'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import { Panel } from '../ui/Panel'

interface Props {
  projectId: string
  preview: JiraPreviewData | null
  /** Why connecting to the company default failed, if it did. */
  connectError?: string | null
  onConnected: (preview: JiraPreviewData) => void
}

/** Which Jira project this project's development stories go to. Connecting only reads the project. */
export function JiraProjectPanel({ projectId, preview, connectError, onConnected }: Props) {
  const inputId = useId()
  const settings = preview?.settings ?? null
  const defaultKey = preview?.default_project_key ?? null
  const [editing, setEditing] = useState(false)
  const [key, setKey] = useState(settings?.project_key ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function connect() {
    setBusy(true)
    setError(null)
    try {
      onConnected(await api.connectJiraProject(projectId, key))
      setEditing(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not connect the Jira project')
    } finally {
      setBusy(false)
    }
  }

  const showForm = editing || !settings
  return (
    <Panel
      title="Jira project"
      description="Where these development stories are sent. Sending happens from Publish & export, after a preview, and only when you confirm."
      actions={
        settings && !editing ? (
          <Button variant="ghost" size="sm" icon="edit" onClick={() => { setKey(settings.project_key); setEditing(true) }}>
            Change
          </Button>
        ) : undefined
      }
    >
      {settings && !editing && (
        <div className="jira-project">
          <p className="jira-project__line">
            <Badge tone="success" icon="check">Connected</Badge>{' '}
            <strong>{settings.project_key}</strong> · {settings.project_name}
            {settings.project_key === defaultKey && <> · <span className="jira-project__meta">company default</span></>}
            {settings.site_url && (
              <>
                {' '}on{' '}
                <a href={`${settings.site_url}/browse/${settings.project_key}`} target="_blank" rel="noreferrer">
                  {settings.site_url.replace(/^https?:\/\//, '')} <Icon name="external" size={14} />
                </a>
              </>
            )}
          </p>
          <p className="jira-project__meta">
            Sent as: epic → {settings.issue_types.epic}, development story → {settings.issue_types.story}, technical
            task → {settings.issue_types.subtask}.{' '}
            {settings.story_points_field
              ? `Story points go to “${settings.story_points_field}”.`
              : 'This project has no story points field on its stories, so points aren’t sent.'}{' '}
            <a href={projectHref(projectId, 'publish')}>Send to Jira from Publish & export</a>.
          </p>
        </div>
      )}
      {showForm && (
        <form
          className="jira-project__form"
          onSubmit={(e) => {
            e.preventDefault()
            if (key.trim()) connect()
          }}
        >
          <label htmlFor={inputId}>Jira project key</label>
          <div className="jira-project__row">
            <input
              id={inputId}
              value={key}
              onChange={(e) => setKey(e.target.value.toUpperCase())}
              placeholder="e.g. TK"
              maxLength={20}
              autoComplete="off"
              spellCheck={false}
              disabled={busy}
            />
            <Button type="submit" variant="primary" size="sm" loading={busy} disabled={!key.trim()}>
              Connect
            </Button>
            {settings && (
              <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => { setEditing(false); setError(null) }}>
                Cancel
              </Button>
            )}
          </div>
          <p className="jira-project__meta">
            The key is the prefix of the project’s issue numbers (TK in TK-146). Connecting checks the project on the
            company’s Atlassian site with the same account as Confluence; it doesn’t change anything in Jira.
            {defaultKey
              ? ` New projects connect to the company default, ${defaultKey}, automatically.`
              : ' A PM can set a company default key on the Settings page.'}
          </p>
        </form>
      )}
      {error && <Banner tone="danger">{error}</Banner>}
      {!settings && connectError && !error && <Banner tone="warning">{connectError}</Banner>}
    </Panel>
  )
}
