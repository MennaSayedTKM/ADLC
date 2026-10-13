import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { DesignUpload } from '../components/validate/DesignUpload'
import { FindingItem } from '../components/validate/FindingItem'
import { ScreenViewer } from '../components/validate/ScreenViewer'
import { TopbarActions } from '../components/shell/ShellContext'
import { Badge } from '../components/ui/Badge'
import { Banner } from '../components/ui/Banner'
import { Button, ButtonLink } from '../components/ui/Button'
import { LockedState } from '../components/ui/LockedState'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { IndeterminateBar, Ring } from '../components/ui/Progress'
import { ALIGNMENT_LABEL, openFindings, summarizeAlignment } from '../lib/design'
import { downloadTextFile, plural, toCsv } from '../lib/format'
import { isApproved } from '../lib/lifecycle'
import { projectHref } from '../lib/router'
import { useElapsed } from '../lib/useElapsed'
import { useProject } from '../state/ProjectContext'
import './ValidatePage.css'

const TONE = { aligned: 'success', partial: 'warning', misaligned: 'danger' } as const

export function ValidatePage({ query }: { query?: URLSearchParams }) {
  const { project, requirements, design, validation, runValidation, clearValidationError, setDesign } = useProject()
  const requestedScreen = Number(query?.get('screen')) || null
  const [selectedPage, setSelectedPage] = useState<number | null>(requestedScreen)
  const [activeFindingId, setActiveFindingId] = useState<string | null>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const elapsed = useElapsed(validation.status === 'running' ? validation.startedAt : null)

  // A new design check starts on the screen that most needs attention.
  const designId = design?.document.id
  useEffect(() => {
    if (!design) return
    const first = design.reports.find((r) => r.status !== 'aligned') ?? design.reports[0]
    setSelectedPage(requestedScreen ?? first?.page ?? null)
    setActiveFindingId(null)
    // Reset only when a different design check loads or a link names a screen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [designId, requestedScreen])

  if (requirements === undefined || design === undefined) return <p className="page-status">Loading…</p>

  if (requirements === null || !isApproved(requirements)) {
    return (
      <LockedState
        icon="target"
        title="Check a design against your requirements"
        body="Upload screens exported from Figma (PDF or image). We’ll tell you which stories each screen covers."
        checklist={[
          { label: requirements ? `Approve requirements v${requirements.document.version}` : 'Approve requirements', done: false },
          { label: 'Upload your screens', done: false },
        ]}
        ctaLabel="Approve requirements first"
        ctaHref={projectHref(project.id, requirements ? 'requirements' : 'sources')}
      />
    )
  }

  const approvedVersion = requirements.document.version

  if (design === null) {
    return (
      <div className="page">
        <PageHeader title="Does the design match what you approved?" description="Upload your screens and we’ll compare each one with your approved stories." />
        <DesignUpload
          validation={validation}
          requirementsVersion={approvedVersion}
          onFile={runValidation}
          onDismissError={clearValidationError}
        />
      </div>
    )
  }

  const summary = summarizeAlignment(design.reports)
  const report = design.reports.find((r) => r.page === selectedPage) ?? design.reports[0]
  const openCount = design.reports.reduce((n, r) => n + openFindings(r).length, 0)
  const totalFindings = design.reports.reduce((n, r) => n + r.findings.length, 0)
  const checkedAgainst = design.requirements_document_id === requirements.document.id ? approvedVersion : null

  async function setFindingStatus(findingId: string, status: 'resolved' | 'dismissed' | 'open') {
    setDesign(await api.updateFindingStatus(project.id, design!.document.id, findingId, status))
  }

  function exportReport() {
    const rows = design!.reports.flatMap((r) =>
      r.findings.length === 0
        ? [[`Screen ${r.page}`, ALIGNMENT_LABEL[r.status], '', '', '', '']]
        : r.findings.map((f) => [`Screen ${r.page}`, ALIGNMENT_LABEL[r.status], f.requirement_external_id ?? '', f.issue, f.recommendation, f.resolution_status]),
    )
    downloadTextFile(
      `design-validation-${design!.document.source_filename.replace(/\.[^.]+$/, '')}.csv`,
      toCsv([['Screen', 'Status', 'Story', 'Issue', 'Recommendation', 'Resolution'], ...rows]),
    )
  }

  return (
    <div className="page">
      <TopbarActions>
        <input
          ref={uploadRef}
          type="file"
          hidden
          accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) runValidation(file)
            e.target.value = ''
          }}
        />
        <Button variant="secondary" size="sm" icon="upload" disabled={validation.status === 'running'} onClick={() => uploadRef.current?.click()} title="Upload a new export to check again">
          Upload new screens
        </Button>
        <Button variant="secondary" size="sm" icon="download" onClick={exportReport}>
          Export report
        </Button>
        <ButtonLink variant="primary" size="sm" iconAfter="arrow-right" href={projectHref(project.id, 'requirements')}>
          Update requirements
        </ButtonLink>
      </TopbarActions>

      <PageHeader
        title="Does the design match what you approved?"
        description={`We compared ${plural(summary.total, 'screen')} against requirements${checkedAgainst ? ` v${checkedAgainst}` : ''}. Here’s what lines up and what needs attention.`}
      />

      {validation.status === 'running' && (
        <Banner tone="info">
          <div className="validate-running" role="status" aria-live="polite">
            <strong>Checking your new screens… {elapsed}</strong>
            <IndeterminateBar label="Checking the design" />
            <span>You can keep working here — the results below will update when it’s done.</span>
          </div>
        </Banner>
      )}
      {validation.status === 'failed' && (
        <Banner
          tone="danger"
          action={
            <Button size="sm" variant="secondary" onClick={clearValidationError}>
              Dismiss
            </Button>
          }
        >
          <strong>We couldn’t check the new screens.</strong> {validation.error} Your previous results are unchanged.
        </Banner>
      )}

      <div className="validate-summary">
        <Panel className="validate-summary__score">
          <div className="validate-summary__ring">
            <Ring
              value={summary.percent}
              tone={summary.percent >= 70 ? 'success' : summary.percent >= 40 ? 'warning' : 'danger'}
              label={`${summary.percent} percent aligned`}
            />
            <div>
              <p className="validate-summary__verdict">{summary.verdict}</p>
              <p className="validate-summary__detail">
                {summary.aligned} of {summary.total} screens fully aligned
              </p>
            </div>
          </div>
          <p className="validate-summary__how">Aligned screens count fully, partly aligned screens count half.</p>
        </Panel>

        <Panel className="validate-summary__chips" title="By screen">
          <div className="validate-chips">
            <Badge tone="success" icon="check">{summary.aligned} aligned</Badge>
            <Badge tone="warning" icon="alert">{summary.partial} partial</Badge>
            <Badge tone="danger" icon="x">{summary.misaligned} {summary.misaligned === 1 ? 'gap' : 'gaps'}</Badge>
          </div>
        </Panel>

        <Panel className="validate-summary__open" title="Findings">
          <p className="validate-summary__count tabular">
            {openCount} <span>open</span>
          </p>
          <p className="validate-summary__detail">
            {totalFindings - openCount} of {totalFindings} resolved or dismissed
          </p>
        </Panel>
      </div>

      <div className="validate-layout">
        <nav className="screen-rail" aria-label="Screens">
          <p className="screen-rail__heading">Screens</p>
          {design.reports.map((r) => {
            const active = r.page === report.page
            return (
              <button
                key={r.id}
                type="button"
                className={`screen-rail__item ${active ? 'screen-rail__item--active' : ''}`}
                aria-current={active ? 'true' : undefined}
                onClick={() => {
                  setSelectedPage(r.page)
                  setActiveFindingId(null)
                }}
              >
                <img
                  className="screen-rail__thumb"
                  src={api.screenImageUrl(project.id, design.document.id, r.page)}
                  alt=""
                  loading="lazy"
                />
                <span className="screen-rail__text">
                  <span className="screen-rail__name">Screen {r.page}</span>
                  <span className="screen-rail__meta">{plural(openFindings(r).length, 'open finding')}</span>
                </span>
                <Badge tone={TONE[r.status]} icon={r.status === 'aligned' ? 'check' : 'alert'}>
                  {ALIGNMENT_LABEL[r.status]}
                </Badge>
              </button>
            )
          })}
        </nav>

        <section className="screen-stage" aria-label={`Screen ${report.page}`}>
          <header className="screen-stage__header">
            <h2 className="screen-stage__title">Screen {report.page}</h2>
            <Badge tone={TONE[report.status]} icon={report.status === 'aligned' ? 'check' : 'alert'}>
              {report.status === 'aligned' ? 'Aligned' : report.status === 'partial' ? 'Partially aligned' : 'Not aligned'}
            </Badge>
          </header>
          <ScreenViewer
            report={report}
            imageUrl={api.screenImageUrl(project.id, design.document.id, report.page)}
            activeFindingId={activeFindingId}
            onSelectFinding={(id) => setActiveFindingId((prev) => (prev === id ? null : id))}
          />
        </section>

        <aside className="findings" aria-label="Findings">
          <h2 className="findings__title">
            Findings <span className="findings__count">· {report.findings.length}</span>
          </h2>
          {report.findings.length === 0 ? (
            <p className="findings__empty">No findings — this screen satisfies the requirements it relates to.</p>
          ) : (
            <ol className="findings__list">
              {report.findings.map((finding, index) => (
                <FindingItem
                  key={finding.id}
                  number={index + 1}
                  projectId={project.id}
                  finding={finding}
                  screenStatus={report.status}
                  active={finding.id === activeFindingId}
                  onSelect={() => setActiveFindingId((prev) => (prev === finding.id ? null : finding.id))}
                  onSetStatus={setFindingStatus}
                />
              ))}
            </ol>
          )}
        </aside>
      </div>
    </div>
  )
}
