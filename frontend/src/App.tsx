import { AppShell } from './components/shell/AppShell'
import { ShellProvider } from './components/shell/ShellContext'
import { Banner } from './components/ui/Banner'
import { ButtonLink } from './components/ui/Button'
import { PageHeader } from './components/ui/PageHeader'
import { HOME_HREF, useRoute } from './lib/router'
import { ProjectLayout } from './pages/ProjectLayout'
import { ProjectsHomePage } from './pages/ProjectsHomePage'
import { SettingsPage } from './pages/SettingsPage'
import { StandingPoliciesPage } from './pages/StandingPoliciesPage'
import { AppProvider, useApp } from './state/AppContext'
import { ProjectProvider } from './state/ProjectContext'

function Routes() {
  const route = useRoute()
  const { projects, loaded, error } = useApp()

  if (route.name === 'project') {
    const project = projects.find((p) => p.id === route.projectId)

    if (!project) {
      return (
        <AppShell route={{ name: 'home' }}>
          {!loaded ? (
            <p className="page-status">Loading…</p>
          ) : (
            <div className="page">
              <PageHeader title="Project not found" description="It may have been removed, or the link is out of date." />
              {error && <Banner tone="danger">{error}</Banner>}
              <div>
                <ButtonLink variant="primary" href={HOME_HREF}>
                  Back to projects
                </ButtonLink>
              </div>
            </div>
          )}
        </AppShell>
      )
    }

    // Keyed so switching projects starts from a clean slate (no stale stories from the last one).
    return (
      <ProjectProvider key={project.id} project={project}>
        <AppShell route={route}>
          <ProjectLayout page={route.page} query={route.query} />
        </AppShell>
      </ProjectProvider>
    )
  }

  return (
    <AppShell route={route}>
      {route.name === 'standards' && <StandingPoliciesPage />}
      {route.name === 'settings' && <SettingsPage />}
      {route.name === 'home' && <ProjectsHomePage />}
    </AppShell>
  )
}

export default function App() {
  return (
    <AppProvider>
      <ShellProvider>
        <Routes />
      </ShellProvider>
    </AppProvider>
  )
}
