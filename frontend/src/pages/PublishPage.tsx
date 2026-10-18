import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { JiraPreview } from '../components/publish/JiraPreview'
import { JiraSendPanel } from '../components/publish/JiraSendPanel'
import { Badge } from '../components/ui/Badge'
import { Banner } from '../components/ui/Banner'
import { Button } from '../components/ui/Button'
import { Icon, type IconName } from '../components/ui/Icon'
import { LockedState } from '../components/ui/LockedState'
import { Modal } from '../components/ui/Modal'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { relativeTime } from '../lib/format'
import { confluenceInfo, isApproved } from '../lib/lifecycle'
import { projectHref } from '../lib/router'
import { useProject } from '../state/ProjectContext'
import { useJiraPreview } from '../state/useJiraPreview'
import { usePublishHistory } from '../state/usePublishHistory'
import './PublishPage.css'

type Destination = 'pdf' | 'confluence' | 'jira'
type PdfFormat = 'business' | 'delivery'

const PDF_FORMATS: { value: PdfFormat; title: string; body: string }[] = [
  {
    value: 'business',
    title: 'Business requirements document',
    body: 'For stakeholders to review and sign off: user stories, acceptance criteria and a use-case diagram for each story.',
  },
  {
    value: 'delivery',
    title: 'Delivery document',
    body: 'For the delivery team: stories with their scenarios, error handling and gaps.',
  },
]

async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data?.detail === 'string') return data.detail
  } catch {
    // not JSON — fall through
  }
  return res.statusText || `The export failed (${res.status})`
}

function DestinationCard({
  icon,
  title,
  body,
  badge,
  selected,
  disabled,
  onSelect,
}: {
  icon: IconName
  title: string
  body: string
  badge: React.ReactNode
  selected: boolean
  disabled?: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={`destination ${selected ? 'destination--selected' : ''} ${disabled ? 'destination--disabled' : ''}`}
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
    >
      <span className="destination__top">
        <span className="destination__icon" aria-hidden="true">
          <Icon name={icon} size={22} />
        </span>
        <span className="destination__title">{title}</span>
        {badge}
      </span>
      <span className="destination__body">{body}</span>
    </button>
  )
}

export function PublishPage() {
  const { project, requirements, reloadRequirements } = useProject()
  const history = usePublishHistory(project.id, requirements)
  const jira = useJiraPreview(project.id)
  const [destination, setDestination] = useState<Destination>('pdf')
  const [format, setFormat] = useState<PdfFormat>('business')
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [publishError, setPublishError] = useState<string | null>(null)

  if (requirements === undefined) return <p className="page-status">Loading…</p>

  if (requirements === null || !isApproved(requirements)) {
    return (
      <LockedState
        icon="send"
        title="Publishing unlocks after approval"
        body="Exports are made from an approved version, so what you share is exactly what the team signed off."
        checklist={[
          { label: 'Generate requirements', done: requirements !== null },
          { label: 'Review the stories and fix any gaps', done: false },
          { label: 'Approve a version', done: false },
        ]}
        ctaLabel={requirements ? 'Review & approve' : 'Add sources'}
        ctaHref={projectHref(project.id, requirements ? 'requirements' : 'sources')}
      />
    )
  }

  const doc = requirements.document
  const published = confluenceInfo(requirements)

  async function downloadPdf() {
    setDownloading(true)
    setDownloadError(null)
    try {
      const res = await fetch(api.exportPdfUrl(project.id, doc.id, format))
      if (!res.ok) throw new Error(await readError(res))
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${project.name.replace(/\s+/g, '_')}_${format}_requirements_v${doc.version}.pdf`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : 'The PDF could not be created')
    } finally {
      setDownloading(false)
    }
  }

  async function publishToConfluence() {
    setPublishing(true)
    setPublishError(null)
    try {
      await api.publishToConfluence(project.id, doc.id)
      await reloadRequirements()
      setConfirmOpen(false)
    } catch (err) {
      setPublishError(
        err instanceof ApiError && err.status === 502
          ? `${err.message} Check that Confluence is connected for this installation.`
          : err instanceof Error
            ? err.message
            : 'Could not publish to Confluence',
      )
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div className="page">
      <PageHeader title="Share your work" description="Choose where it should go and what to include. Nothing is sent until you confirm." />

      <div className="destinations" role="group" aria-label="Destination">
        <DestinationCard
          icon="file"
          title="PDF document"
          body="A clean, printable file to email or attach."
          badge={<Badge tone="success" icon="check">Ready</Badge>}
          selected={destination === 'pdf'}
          onSelect={() => setDestination('pdf')}
        />
        <DestinationCard
          icon="link"
          title="Confluence"
          body="Publish as a page in your team space, linked from the project index."
          badge={
            published ? (
              <Badge tone="success" icon="check">Published</Badge>
            ) : (
              <Badge tone="info">Manual publish</Badge>
            )
          }
          selected={destination === 'confluence'}
          onSelect={() => setDestination('confluence')}
        />
        <DestinationCard
          icon="branch"
          title="Jira development stories"
          body="Epics, stories and sub-tasks with coding prompts and screens, from Dev stories."
          badge={
            jira.preview?.settings ? (
              <Badge tone="success" icon="check">{jira.preview.settings.project_key}</Badge>
            ) : (
              <Badge tone="info">Set up</Badge>
            )
          }
          selected={destination === 'jira'}
          onSelect={() => setDestination('jira')}
        />
      </div>

      <div className="publish-layout">
        <div className="publish-layout__main">
          {destination === 'pdf' ? (
            <Panel
              title="What to include"
              description={`Version ${doc.version} · generated fresh each time, so it always matches the approved stories.`}
            >
              <div className="format-options" role="radiogroup" aria-label="PDF format">
                {PDF_FORMATS.map((option) => (
                  <label key={option.value} className={`format-option ${format === option.value ? 'format-option--selected' : ''}`}>
                    <input type="radio" name="pdf-format" checked={format === option.value} onChange={() => setFormat(option.value)} />
                    <span>
                      <span className="format-option__title">{option.title}</span>
                      <span className="format-option__body">{option.body}</span>
                    </span>
                  </label>
                ))}
              </div>
              <p className="publish-note">
                The design validation report isn’t part of the PDF — export it from <a href={projectHref(project.id, 'validate')}>Validate design</a>.
              </p>
              {downloadError && <Banner tone="danger">{downloadError}</Banner>}
              <div className="publish-actions">
                <Button variant="primary" size="lg" icon="download" loading={downloading} onClick={downloadPdf}>
                  {downloading ? 'Creating PDF…' : 'Download PDF'}
                </Button>
                {downloading && format === 'business' && (
                  <span className="publish-note">Drawing the use-case diagrams can take a minute the first time.</span>
                )}
              </div>
            </Panel>
          ) : destination === 'jira' ? (
            <JiraSendPanel
              projectId={project.id}
              preview={jira.preview}
              loading={jira.loading}
              error={jira.error}
              onChanged={jira.setPreview}
              refresh={jira.refresh}
            />
          ) : (
            <Panel title="Confluence" description="Each approved version becomes its own page under this project’s index page.">
              {published ? (
                <Banner
                  tone="success"
                  action={
                    <a className="btn btn--secondary btn--sm" href={published.page_url} target="_blank" rel="noreferrer">
                      View on Confluence <Icon name="external" size={15} />
                    </a>
                  }
                >
                  <strong>Version {doc.version} is published.</strong> Last published {relativeTime(published.published_at)}.
                </Banner>
              ) : (
                <>
                  <ul className="publish-facts">
                    <li>
                      <Icon name="check" size={16} /> Creates one page for version {doc.version}
                    </li>
                    <li>
                      <Icon name="check" size={16} /> Includes the user stories, acceptance criteria and use-case diagrams
                    </li>
                    <li>
                      <Icon name="check" size={16} /> Nothing is overwritten — a newer version creates a new page
                    </li>
                  </ul>
                  <div className="publish-actions">
                    <Button variant="primary" size="lg" icon="send" onClick={() => setConfirmOpen(true)}>
                      Publish to Confluence
                    </Button>
                  </div>
                </>
              )}
              <p className="publish-note">The Confluence space and connection are set up by whoever installs this tool.</p>
            </Panel>
          )}
        </div>

        <aside className="publish-layout__side">
          <JiraPreview />
          <Panel title="Publish history">
            {history.loading ? (
              <p className="publish-note">Loading…</p>
            ) : history.events.length === 0 ? (
              <p className="publish-note">Nothing has been published to Confluence yet. PDF downloads aren’t recorded.</p>
            ) : (
              <ul className="history">
                {history.events.map((event) => (
                  <li key={event.version} className="history__item">
                    <span className="history__version">v{event.version}</span>
                    <span className="history__text">
                      <a href={event.url} target="_blank" rel="noreferrer">
                        Confluence
                      </a>{' '}
                      · {relativeTime(event.at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </aside>
      </div>

      <Modal
        open={confirmOpen}
        onClose={() => !publishing && setConfirmOpen(false)}
        title={`Publish version ${doc.version} to Confluence?`}
        description="This creates a page in your Confluence space that your team can see."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)} disabled={publishing}>
              Cancel
            </Button>
            <Button variant="primary" icon="send" loading={publishing} onClick={publishToConfluence}>
              Publish now
            </Button>
          </>
        }
      >
        <p className="publish-note">Only publish when you’re ready to share it. You can’t unpublish from here.</p>
        {publishError && <Banner tone="danger">{publishError}</Banner>}
      </Modal>
    </div>
  )
}
