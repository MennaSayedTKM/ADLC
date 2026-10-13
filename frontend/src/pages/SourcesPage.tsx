import { useEffect, useRef } from 'react'
import { ClientQuestions } from '../components/sources/ClientQuestions'
import { ReadinessPanel } from '../components/sources/ReadinessPanel'
import { SourceIntake } from '../components/sources/SourceIntake'
import { Banner } from '../components/ui/Banner'
import { ButtonLink } from '../components/ui/Button'
import { ComingSoon } from '../components/ui/ComingSoon'
import { Icon } from '../components/ui/Icon'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { Toggle } from '../components/ui/Toggle'
import { computeReadiness } from '../lib/sources'
import { navigate, projectHref, STANDARDS_HREF } from '../lib/router'
import { useClarifyingQuestions } from '../state/useClarifyingQuestions'
import { useStandards } from '../state/useStandards'
import { useProject } from '../state/ProjectContext'
import './SourcesPage.css'

export function SourcesPage() {
  const { project, resources, requirements, generation, setResources, generateRequirements, clearGenerationError } = useProject()
  const questions = useClarifyingQuestions(project.id)
  const { active: activeStandards } = useStandards()

  const list = resources ?? []
  const generated = requirements !== null && requirements !== undefined
  const readiness = computeReadiness(list, activeStandards.length, questions.questions)

  // When a run that started on this page finishes, take the person to the result.
  const wasRunning = useRef(generation.status === 'running')
  useEffect(() => {
    if (wasRunning.current && generation.status === 'idle' && requirements) {
      navigate(projectHref(project.id, 'requirements'))
    }
    wasRunning.current = generation.status === 'running'
  }, [generation.status, requirements, project.id])

  if (resources === undefined || requirements === undefined) {
    return <p className="page-status">Loading…</p>
  }

  return (
    <div className="page">
      <PageHeader
        title="What do we know so far?"
        description="Add everything related to this project. The more context you give, the better the first draft of your stories will be. You can always add more later."
      />

      {generated && (
        <Banner
          tone="info"
          action={
            <ButtonLink size="sm" variant="secondary" href={projectHref(project.id, 'requirements')} iconAfter="arrow-right">
              Open requirements
            </ButtonLink>
          }
        >
          <strong>Requirements v{requirements.document.version} were generated from these sources.</strong> To bring in
          new material, file a change request on the Requirements page — it updates the stories without losing your
          edits.
        </Banner>
      )}

      <div className="sources-layout">
        <div className="sources-layout__main">
          <SourceIntake projectId={project.id} resources={list} setResources={setResources} locked={generated} />
          <ClientQuestions
            projectName={project.name}
            questions={questions.questions}
            generating={questions.generating}
            error={questions.error}
            hasSources={list.length > 0}
            readOnly={generated}
            onGenerate={questions.generate}
            onUpdate={questions.update}
          />
        </div>

        <aside className="sources-layout__aside" aria-label="Readiness and standards">
          {!generated && (
            <ReadinessPanel
              readiness={readiness}
              generation={generation}
              onGenerate={generateRequirements}
              onDismissError={clearGenerationError}
            />
          )}

          <Panel
            title="Company standards in use"
            actions={
              <a className="link-button" href={STANDARDS_HREF}>
                Manage
              </a>
            }
          >
            {activeStandards.length === 0 ? (
              <p className="standards-empty">No company standards are switched on.</p>
            ) : (
              <ul className="standards-chips">
                {activeStandards.map((s) => (
                  <li key={s.id} className="standards-chip">
                    <Icon name="shield" size={14} /> {s.title}
                  </li>
                ))}
              </ul>
            )}
            <p className="standards-note">Your client’s own documents always take priority over these.</p>
          </Panel>

          <Panel
            title={
              <span className="settings-title">
                Generation settings <ComingSoon />
              </span>
            }
            tone="sunken"
          >
            <label className="setting-row">
              <span>
                <span className="setting-row__label">Read images and diagrams</span>
                <span className="setting-row__hint">Whiteboard photos and screenshots are always read today.</span>
              </span>
              <Toggle checked disabled onChange={() => undefined} label="Read images and diagrams" />
            </label>
            <label className="setting-row">
              <span>
                <span className="setting-row__label">Deep analysis</span>
                <span className="setting-row__hint">A slower, more thorough pass.</span>
              </span>
              <Toggle checked={false} disabled onChange={() => undefined} label="Deep analysis" />
            </label>
          </Panel>
        </aside>
      </div>
    </div>
  )
}
