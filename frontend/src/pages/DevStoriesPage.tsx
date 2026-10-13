import { JiraPreview } from '../components/publish/JiraPreview'
import { ButtonLink } from '../components/ui/Button'
import { ComingSoon } from '../components/ui/ComingSoon'
import { PageHeader } from '../components/ui/PageHeader'
import { projectHref } from '../lib/router'
import { useProject } from '../state/ProjectContext'

/** Placeholder for the planned development-stories module: shows the direction, does nothing. */
export function DevStoriesPage() {
  const { project } = useProject()

  return (
    <div className="page">
      <PageHeader
        title="Dev stories"
        description={
          <>
            Turn approved requirements into epics and stories for your development team, with acceptance criteria
            carried over. <ComingSoon label="Coming soon" />
          </>
        }
        actions={
          <ButtonLink variant="secondary" href={projectHref(project.id, 'publish')} iconAfter="arrow-right">
            Go to Publish &amp; export
          </ButtonLink>
        }
      />
      <JiraPreview />
    </div>
  )
}
