import { useEffect, useState } from 'react'
import { ChangeRequestPanel } from '../components/ChangeRequestPanel'
import { EvaluationPanel } from '../components/EvaluationPanel'
import { GapPanel } from '../components/GapPanel'
import { ApproveDialog } from '../components/requirements/ApproveDialog'
import { CompareDrawer } from '../components/requirements/CompareDrawer'
import { DiagramsTab } from '../components/requirements/DiagramsTab'
import { EpicRail } from '../components/requirements/EpicRail'
import { ReviewSummary } from '../components/requirements/ReviewSummary'
import { StoryWorkspace } from '../components/requirements/StoryWorkspace'
import { SuggestionsAside } from '../components/requirements/SuggestionsAside'
import { TraceabilityTable } from '../components/requirements/TraceabilityTable'
import { TopbarActions } from '../components/shell/ShellContext'
import { SuggestionsPanel } from '../components/SuggestionsPanel'
import { Badge } from '../components/ui/Badge'
import { Banner } from '../components/ui/Banner'
import { Button, ButtonLink } from '../components/ui/Button'
import { Icon } from '../components/ui/Icon'
import { Modal } from '../components/ui/Modal'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { TabPanel, Tabs } from '../components/ui/Tabs'
import { plural } from '../lib/format'
import { isApproved } from '../lib/lifecycle'
import { projectHref } from '../lib/router'
import { useProject } from '../state/ProjectContext'
import { useRequirementsActions } from '../state/useRequirementsActions'
import './RequirementsPage.css'

type ReviewTab = 'stories' | 'diagrams' | 'gaps' | 'trace'
const TABS: ReviewTab[] = ['stories', 'diagrams', 'gaps', 'trace']

function tabFromQuery(query?: URLSearchParams): ReviewTab {
  const requested = query?.get('tab') as ReviewTab | null
  return requested && TABS.includes(requested) ? requested : 'stories'
}

export function RequirementsPage({ query }: { query?: URLSearchParams }) {
  const { project, requirements, design, resources, generation } = useProject()
  const actions = useRequirementsActions()

  const [tab, setTab] = useState<ReviewTab>(() => tabFromQuery(query))
  // `undefined` means "no choice yet": the page opens on the first epic, because a long
  // project is easier to review one epic at a time. `null` is the explicit "every story".
  const [chosenEpic, setSelectedEpic] = useState<string | null | undefined>(query?.get('epic') ?? undefined)
  const selectedEpic = chosenEpic === undefined ? (requirements?.epics[0]?.external_id ?? null) : chosenEpic
  const [approveOpen, setApproveOpen] = useState(false)
  const [compareOpen, setCompareOpen] = useState(false)
  const [qualityOpen, setQualityOpen] = useState(false)
  const [changeRequestOpen, setChangeRequestOpen] = useState(false)
  const [justApproved, setJustApproved] = useState(false)

  const queryKey = query?.toString() ?? ''
  const focusStory = query?.get('story') ?? null

  // Links and ⌘K results can point at a tab, an epic or a single story.
  useEffect(() => {
    setTab(tabFromQuery(query))
    const story = requirements?.stories.find((s) => s.external_id === focusStory)
    const storyEpic = story ? requirements?.epics.find((e) => e.id === story.parent_id)?.external_id ?? null : null
    setSelectedEpic(query?.get('epic') ?? storyEpic ?? undefined)
    if (focusStory) {
      setTab('stories')
      window.setTimeout(() => document.getElementById(`story-${focusStory}`)?.scrollIntoView({ block: 'center' }), 80)
    }
    // Only react to the URL changing, not to every edit of the requirements.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey])

  if (requirements === undefined || resources === undefined) {
    return <p className="page-status">Loading…</p>
  }

  if (requirements === null) {
    return (
      <div className="page">
        <PageHeader title="Review your requirements" description="Your stories will appear here once they’re generated." />
        <Panel tone="sunken" className="req-empty">
          <Icon name="list" size={28} />
          <h2 className="req-empty__title">{generation.status === 'running' ? 'Generating your requirements…' : 'Nothing to review yet'}</h2>
          <p className="req-empty__body">
            {generation.status === 'running'
              ? 'This takes a couple of minutes. You can stay here — the stories will appear when they’re ready.'
              : 'Add your sources and generate requirements. We’ll draft the stories, flag the gaps and bring you back here to review.'}
          </p>
          <ButtonLink variant="primary" href={projectHref(project.id, 'sources')} iconAfter="arrow-right">
            {generation.status === 'running' ? 'See progress' : 'Go to sources'}
          </ButtonLink>
        </Panel>
      </div>
    )
  }

  const detail = requirements
  const doc = detail.document
  const approved = isApproved(detail)
  const openGaps = detail.unresolved_gap_count
  const pendingIdeas = detail.suggestions.filter((s) => s.type === 'story').length
  const previousLabel = doc.previous_version_id ? `Compare with v${doc.version - 1}` : null

  async function approve() {
    await actions.approve()
    setJustApproved(true)
    setTab('stories')
  }

  return (
    <div className="page">
      <TopbarActions>
        <Badge tone={approved ? 'success' : 'neutral'} icon={approved ? 'lock' : 'edit'}>
          {approved ? `Approved v${doc.version}` : `Draft v${doc.version}`}
        </Badge>
        {previousLabel && (
          <Button variant="secondary" size="sm" icon="compare" onClick={() => setCompareOpen(true)}>
            {previousLabel}
          </Button>
        )}
        {approved ? (
          <ButtonLink variant="primary" size="sm" icon="send" href={projectHref(project.id, 'publish')}>
            Publish &amp; export
          </ButtonLink>
        ) : (
          <Button variant="primary" size="sm" icon="check" onClick={() => setApproveOpen(true)}>
            Approve this version
          </Button>
        )}
      </TopbarActions>

      <PageHeader
        title="Review your requirements"
        description={`${plural(detail.stories.length, 'story', 'stories')} in ${plural(detail.epics.length, 'epic')}, drafted from your ${plural(resources.length, 'source')}. ${
          approved ? 'This version is approved.' : 'Check them, fix the gaps, then approve to unlock design.'
        }`}
        actions={
          <>
            <Button variant="secondary" icon="download" onClick={() => setChangeRequestOpen(true)}>
              File a change request
            </Button>
          </>
        }
      />

      {actions.forkNotice && <Banner tone="info">{actions.forkNotice}</Banner>}
      {approved && !actions.forkNotice && !justApproved && (
        <Banner tone="info">
          This version is approved and locked. Editing a story creates a new draft version rather than changing what was
          approved.
        </Banner>
      )}
      {justApproved && approved && (
        <Banner
          tone="success"
          action={
            <ButtonLink size="sm" variant="primary" href={projectHref(project.id, 'design')} iconAfter="arrow-right">
              Create design prompts
            </ButtonLink>
          }
        >
          <strong>Version {doc.version} is approved.</strong> Design is unlocked — your stories are now locked in.
        </Banner>
      )}

      <ReviewSummary detail={detail} approved={approved} onOpenQuality={() => setQualityOpen(true)} onOpenGaps={() => setTab('gaps')} />

      <Tabs<ReviewTab>
        label="Requirements sections"
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'stories', label: 'User stories' },
          { id: 'diagrams', label: 'Use case diagrams' },
          { id: 'gaps', label: 'Gaps & suggestions', count: openGaps + pendingIdeas, alert: openGaps > 0 },
          { id: 'trace', label: 'Traceability' },
        ]}
      />

      <TabPanel id="stories" active={tab === 'stories'}>
        <div className="review-layout">
          <EpicRail
            projectId={project.id}
            docId={doc.id}
            epics={detail.epics}
            stories={detail.stories}
            selected={selectedEpic}
            onSelect={setSelectedEpic}
            onCreateEpic={actions.createEpic}
          />
          <StoryWorkspace
            key={focusStory ?? 'none'}
            projectId={project.id}
            detail={detail}
            selectedEpic={selectedEpic}
            focusStory={focusStory}
            onSaveItem={actions.saveItem}
            onCreateStory={actions.createStory}
            onDeleteItem={actions.deleteItem}
          />
          <SuggestionsAside
            detail={detail}
            onSeeAll={() => setTab('gaps')}
            onDismissGap={(id) => actions.setGapStatus(id, 'dismissed')}
            onAccept={actions.acceptSuggestion}
            onDismiss={actions.dismissSuggestion}
          />
        </div>
      </TabPanel>

      <TabPanel id="diagrams" active={tab === 'diagrams'}>
        <DiagramsTab projectId={project.id} docId={doc.id} storyCount={detail.stories.length} />
      </TabPanel>

      <TabPanel id="gaps" active={tab === 'gaps'}>
        <div className="gaps-layout">
          <GapPanel
            projectId={project.id}
            docId={doc.id}
            gaps={detail.gaps}
            epics={detail.epics}
            onSetStatus={actions.setGapStatus}
            onResolveAsStory={actions.resolveGapAsStory}
          />
          <SuggestionsPanel
            suggestions={detail.suggestions}
            epics={detail.epics}
            onAccept={actions.acceptSuggestion}
            onDismiss={actions.dismissSuggestion}
          />
        </div>
      </TabPanel>

      <TabPanel id="trace" active={tab === 'trace'}>
        <TraceabilityTable projectId={project.id} detail={detail} design={design ?? null} />
      </TabPanel>

      <ApproveDialog
        open={approveOpen}
        version={doc.version}
        openGaps={openGaps}
        onClose={() => setApproveOpen(false)}
        onApprove={approve}
        onReviewGaps={() => {
          setApproveOpen(false)
          setTab('gaps')
        }}
      />

      <CompareDrawer open={compareOpen} onClose={() => setCompareOpen(false)} projectId={project.id} current={detail} />

      <Modal
        open={qualityOpen}
        onClose={() => setQualityOpen(false)}
        variant="drawer"
        title="Quality check"
        description="How clear the client’s material was, and how good the drafted stories are."
      >
        <EvaluationPanel evaluation={detail.evaluation} onRun={actions.runEvaluation} />
      </Modal>

      <Modal
        open={changeRequestOpen}
        onClose={() => setChangeRequestOpen(false)}
        title="File a change request"
        description="Upload the change request document. It’s merged into a new draft version — nothing approved is overwritten."
      >
        <ChangeRequestPanel
          projectId={project.id}
          defaultOpen
          onCancel={() => setChangeRequestOpen(false)}
          onFiled={async (result) => {
            await actions.changeRequestFiled(result)
            setChangeRequestOpen(false)
          }}
        />
      </Modal>
    </div>
  )
}
