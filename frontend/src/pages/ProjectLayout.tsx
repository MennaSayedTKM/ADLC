import { Stepper } from '../components/shell/Stepper'
import type { ProjectPage } from '../lib/router'
import { useProject } from '../state/ProjectContext'
import { DesignPage } from './DesignPage'
import { DevStoriesPage } from './DevStoriesPage'
import { ProjectOverviewPage } from './ProjectOverviewPage'
import { PublishPage } from './PublishPage'
import { RequirementsPage } from './RequirementsPage'
import { SourcesPage } from './SourcesPage'
import { ValidatePage } from './ValidatePage'

/** Every project page sits under the lifecycle stepper, so progress is always in view. */
export function ProjectLayout({ page, query }: { page: ProjectPage; query: URLSearchParams }) {
  const { project, steps, ready } = useProject()

  return (
    <div className="page">
      <Stepper projectId={project.id} steps={steps} loading={!ready} />
      {page === 'overview' && <ProjectOverviewPage />}
      {page === 'sources' && <SourcesPage />}
      {page === 'requirements' && <RequirementsPage query={query} />}
      {page === 'design' && <DesignPage />}
      {page === 'validate' && <ValidatePage query={query} />}
      {page === 'publish' && <PublishPage />}
      {page === 'dev-stories' && <DevStoriesPage />}
    </div>
  )
}
