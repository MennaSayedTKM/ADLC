import { useMemo, useState } from 'react'
import { NewProjectDialog } from '../components/home/NewProjectDialog'
import { Badge } from '../components/ui/Badge'
import { Banner } from '../components/ui/Banner'
import { Button } from '../components/ui/Button'
import { DropTarget } from '../components/ui/DropTarget'
import { Icon } from '../components/ui/Icon'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { StepSegments } from '../components/ui/Progress'
import { greeting, plural, relativeTime } from '../lib/format'
import { summarizeAlignment } from '../lib/design'
import { isApproved } from '../lib/lifecycle'
import { projectHref } from '../lib/router'
import { useApp } from '../state/AppContext'
import { buildActivity, useAttentionItems, useProjectSummaries, type ProjectSummary } from '../state/useProjectSummaries'
import './ProjectsHomePage.css'

type Filter = 'all' | 'in_progress' | 'published'

function ProjectCard({ summary }: { summary: ProjectSummary }) {
  const { project, requirements, design, steps, stage, published, next } = summary
  const gaps = requirements && !isApproved(requirements) ? requirements.unresolved_gap_count : 0
  const alignment = design ? summarizeAlignment(design.reports) : null

  return (
    <a className="project-card" href={projectHref(project.id, next.page, next.query)}>
      <div className="project-card__top">
        <span className="project-card__avatar" aria-hidden="true">
          {project.name.slice(0, 2).toUpperCase()}
        </span>
        <div className="project-card__title">
          <h3 className="project-card__name">{project.name}</h3>
          <p className="project-card__updated">Updated {relativeTime(summary.updatedAt)}</p>
        </div>
        <Icon name="chevron-right" size={18} className="project-card__chevron" />
      </div>

      <StepSegments states={steps.map((s) => s.state)} label={stage} />
      <p className="project-card__stage">{stage}</p>

      <div className="project-card__chips">
        {requirements && <Badge>{plural(requirements.stories.length, 'story', 'stories')}</Badge>}
        {!requirements && summary.resourceCount > 0 && <Badge>{plural(summary.resourceCount, 'source')}</Badge>}
        {gaps > 0 && (
          <Badge tone="warning" icon="alert">
            {plural(gaps, 'gap')}
          </Badge>
        )}
        {alignment && (
          <Badge tone={alignment.percent >= 70 ? 'success' : 'warning'} icon={alignment.percent >= 70 ? 'check' : 'alert'}>
            {alignment.percent}% aligned
          </Badge>
        )}
        {published && requirements && (
          <Badge tone="success" icon="check">
            Published v{requirements.document.version}
          </Badge>
        )}
      </div>
    </a>
  )
}

export function ProjectsHomePage() {
  const { projects, loaded, error } = useApp()
  const { summaries, loading } = useProjectSummaries(projects)
  const attention = useAttentionItems(summaries)
  const activity = useMemo(() => buildActivity(summaries).slice(0, 5), [summaries])
  const [filter, setFilter] = useState<Filter>('all')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dropped, setDropped] = useState<File[]>([])

  const visible = summaries.filter((s) =>
    filter === 'all' ? true : filter === 'published' ? s.published : !s.published,
  )

  function openDialog(files: File[] = []) {
    setDropped(files)
    setDialogOpen(true)
  }

  const subtitle =
    attention.length > 0
      ? `You have ${plural(attention.length, 'thing')} that ${attention.length === 1 ? 'needs' : 'need'} your decision. Everything else is moving along.`
      : projects.length > 0
        ? 'Nothing needs your decision right now.'
        : 'Start with a document and we’ll draft the user stories and diagrams for you.'

  return (
    <div className="page">
      <PageHeader
        title={greeting()}
        description={subtitle}
        actions={
          <Button variant="primary" size="lg" icon="plus" onClick={() => openDialog()}>
            New project
          </Button>
        }
      />

      {error && <Banner tone="danger">{error}</Banner>}

      <div className="home-hero">
        <DropTarget onFiles={openDialog} className="home-hero__drop">
          {({ open, dragging }) => (
            <Panel tone="accent" className={`start-card ${dragging ? 'start-card--dragging' : ''}`}>
              <div className="start-card__icon" aria-hidden="true">
                <Icon name="upload" size={26} />
              </div>
              <div className="start-card__text">
                <h2 className="start-card__title">Start from any document</h2>
                <p className="start-card__body">
                  Drop a requirements doc, meeting notes or a whiteboard photo. We&rsquo;ll draft the user stories
                  and diagrams for you.
                </p>
              </div>
              <Button variant="secondary" size="lg" onClick={open}>
                Choose files
              </Button>
            </Panel>
          )}
        </DropTarget>

        <Panel title="Needs your attention" className="attention">
          {attention.length === 0 ? (
            <p className="attention__empty">
              <Icon name="check-circle" size={18} /> You&rsquo;re all caught up.
            </p>
          ) : (
            <ul className="attention__list">
              {attention.slice(0, 4).map(({ summary, tone, badge, text }) => (
                <li key={summary.project.id}>
                  <a className="attention__item" href={projectHref(summary.project.id, summary.next.page, summary.next.query)}>
                    <Badge tone={tone} icon={tone === 'warning' ? 'alert' : 'eye'}>
                      {badge}
                    </Badge>
                    <span className="attention__text">
                      <strong>{summary.project.name}</strong> · {text}
                    </span>
                    <Icon name="chevron-right" size={16} />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <section className="home-section" aria-labelledby="projects-heading">
        <div className="home-section__header">
          <h2 id="projects-heading" className="home-section__title">
            Your projects
          </h2>
          <div className="filter-chips" role="group" aria-label="Filter projects">
            {(
              [
                ['all', 'All'],
                ['in_progress', 'In progress'],
                ['published', 'Published'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`filter-chip ${filter === value ? 'filter-chip--active' : ''}`}
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {!loaded || (loading && projects.length > 0) ? (
          <div className="project-grid" aria-busy="true">
            {Array.from({ length: Math.max(1, Math.min(projects.length, 3)) }).map((_, i) => (
              <div key={i} className="project-card project-card--skeleton" />
            ))}
          </div>
        ) : visible.length === 0 ? (
          <Panel tone="sunken" className="home-empty">
            <p className="home-empty__title">
              {projects.length === 0 ? 'No projects yet' : `No ${filter === 'published' ? 'published' : 'in-progress'} projects`}
            </p>
            <p className="home-empty__body">
              {projects.length === 0
                ? 'Create your first project, or drop a document above to get started.'
                : 'Try another filter.'}
            </p>
            {projects.length === 0 && (
              <Button variant="primary" icon="plus" onClick={() => openDialog()}>
                New project
              </Button>
            )}
          </Panel>
        ) : (
          <div className="project-grid">
            {visible.map((s) => (
              <ProjectCard key={s.project.id} summary={s} />
            ))}
          </div>
        )}
      </section>

      {activity.length > 0 && (
        <Panel title="Recent activity" className="activity">
          <ul className="activity__list">
            {activity.map((event) => (
              <li key={event.id}>
                <a className="activity__item" href={projectHref(event.projectId)}>
                  <span className={`activity__icon activity__icon--${event.icon}`} aria-hidden="true">
                    <Icon name={event.icon} size={15} />
                  </span>
                  <span className="activity__text">
                    <strong>{event.subject}</strong> {event.detail}
                  </span>
                  <time className="activity__time" dateTime={event.at}>
                    {relativeTime(event.at)}
                  </time>
                </a>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <NewProjectDialog open={dialogOpen} onClose={() => setDialogOpen(false)} initialFiles={dropped} />
    </div>
  )
}
