import { useMemo } from 'react'
import { Badge } from '../components/ui/Badge'
import { ButtonLink } from '../components/ui/Button'
import { Icon, type IconName } from '../components/ui/Icon'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { plural, relativeTime } from '../lib/format'
import { summarizeAlignment } from '../lib/design'
import { isApproved } from '../lib/lifecycle'
import { projectHref, type ProjectPage } from '../lib/router'
import { useProject } from '../state/ProjectContext'
import { buildActivity } from '../state/useProjectSummaries'
import './ProjectOverviewPage.css'

interface Tile {
  icon: IconName
  label: string
  value: string
  hint: string
  page: ProjectPage
  tone?: 'warning' | 'success'
}

export function ProjectOverviewPage() {
  const { project, resources, requirements, design, next, ready } = useProject()
  const events = useMemo(
    () => buildActivity([{ project, requirements: requirements ?? null, design: design ?? null }]),
    [project, requirements, design],
  )

  // Until every answer is in, "next step" would be a guess (and usually the wrong one).
  if (!ready) return <p className="page-status">Loading…</p>

  const sourceCount = resources?.length ?? 0
  const gaps = requirements && !isApproved(requirements) ? requirements.unresolved_gap_count : 0
  const alignment = design ? summarizeAlignment(design.reports) : null

  const tiles: Tile[] = [
    {
      icon: 'upload',
      label: 'Sources',
      value: String(sourceCount),
      hint: sourceCount === 0 ? 'Nothing added yet' : 'Documents and notes',
      page: 'sources',
    },
    {
      icon: 'list',
      label: 'User stories',
      value: requirements ? String(requirements.stories.length) : '—',
      hint: requirements
        ? `${plural(requirements.epics.length, 'epic')} · v${requirements.document.version}${isApproved(requirements) ? ' approved' : ' draft'}`
        : 'Not generated yet',
      page: 'requirements',
    },
    {
      icon: 'alert',
      label: 'Open gaps',
      value: requirements ? String(requirements.unresolved_gap_count) : '—',
      hint: gaps > 0 ? 'Resolve before approving' : requirements ? 'Nothing blocking' : 'Appear after generating',
      page: 'requirements',
      tone: gaps > 0 ? 'warning' : undefined,
    },
    {
      icon: 'target',
      label: 'Design match',
      value: alignment ? `${alignment.percent}%` : '—',
      hint: alignment ? `${alignment.aligned} of ${alignment.total} screens aligned` : 'Upload screens to check',
      page: 'validate',
      tone: alignment && alignment.percent >= 70 ? 'success' : undefined,
    },
  ]

  return (
    <div className="page">
      <PageHeader title={project.name} description="Where this project stands and what to do next." />

      <Panel tone="accent" className="next-step">
        <div className="next-step__text">
          <p className="next-step__eyebrow">
            <Icon name="sparkles" size={15} /> Next best step
          </p>
          <h2 className="next-step__title">{next.title}</h2>
          <p className="next-step__body">{next.body}</p>
        </div>
        <ButtonLink variant="primary" size="lg" iconAfter="arrow-right" href={projectHref(project.id, next.page, next.query)}>
          {next.label}
        </ButtonLink>
      </Panel>

      <div className="overview-tiles">
        {tiles.map((tile) => (
          <a key={tile.label} className="overview-tile" href={projectHref(project.id, tile.page)}>
            <span className="overview-tile__icon" aria-hidden="true">
              <Icon name={tile.icon} size={18} />
            </span>
            <span className="overview-tile__label">{tile.label}</span>
            <span className={`overview-tile__value tabular ${tile.tone ? `overview-tile__value--${tile.tone}` : ''}`}>
              {tile.value}
            </span>
            <span className="overview-tile__hint">{tile.hint}</span>
          </a>
        ))}
      </div>

      <Panel title="Recent activity">
        {events.length === 0 ? (
          <p className="overview-empty">Nothing has happened yet. Add a source to get started.</p>
        ) : (
          <ul className="overview-activity">
            {events.map((event) => (
              <li key={event.id} className="overview-activity__item">
                <Badge tone="neutral">{relativeTime(event.at)}</Badge>
                <span>
                  <strong>{event.subject}</strong> {event.detail}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}
