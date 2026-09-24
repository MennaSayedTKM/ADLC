import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ChangeRequestIngestResponse, ItemFields, RequirementsDetail, TextIngestResponse } from '../api/types'
import { ApprovalHeader } from '../components/ApprovalHeader'
import { ChangeRequestPanel } from '../components/ChangeRequestPanel'
import { EpicStoryTree } from '../components/EpicStoryTree'
import { ClarifyingQuestionsPanel } from '../components/ClarifyingQuestionsPanel'
import { EvaluationPanel } from '../components/EvaluationPanel'
import { GapPanel } from '../components/GapPanel'
import { ResourceStagingPanel } from '../components/ResourceStagingPanel'
import { RunExtractionPanel } from '../components/RunExtractionPanel'
import { SuggestionsPanel } from '../components/SuggestionsPanel'
import { Banner } from '../components/ui/Banner'
import './RequirementsReviewPage.css'

interface RequirementsReviewPageProps {
  projectId: string
}

export function RequirementsReviewPage({ projectId }: RequirementsReviewPageProps) {
  const [detail, setDetail] = useState<RequirementsDetail | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [forkNotice, setForkNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    setForkNotice(null)
    try {
      const data = await api.getLatestRequirements(projectId)
      setDetail(data)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setDetail(null) // no doc uploaded yet — not an error state
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load requirements')
      }
    }
  }, [projectId])

  useEffect(() => {
    setDetail(undefined)
    load()
  }, [load])

  async function handleExtracted(_result: TextIngestResponse) {
    await load()
  }

  function applyUpdate(previousDocId: string, updated: RequirementsDetail, forkedActionLabel: string) {
    if (updated.document.id !== previousDocId) {
      setForkNotice(
        `That version was already approved, so ${forkedActionLabel} created version ${updated.document.version} instead of changing what was approved.`,
      )
    } else {
      setForkNotice(null)
    }
    setDetail(updated)
  }

  async function handleSaveItem(itemId: string, fields: ItemFields) {
    if (!detail) return
    const previousDocId = detail.document.id
    const updated = await api.updateItem(projectId, previousDocId, itemId, fields)
    applyUpdate(previousDocId, updated, 'your edit')
  }

  async function handleCreateEpic(text: string, fields?: ItemFields) {
    if (!detail) return
    const previousDocId = detail.document.id
    const updated = await api.createItem(projectId, previousDocId, { type: 'epic', text, ...fields })
    applyUpdate(previousDocId, updated, 'adding this epic')
  }

  async function handleCreateStory(parentId: string, fields: ItemFields & { text: string }) {
    if (!detail) return
    const previousDocId = detail.document.id
    const updated = await api.createItem(projectId, previousDocId, {
      type: 'story',
      parent_id: parentId,
      ...fields,
    })
    applyUpdate(previousDocId, updated, 'adding this story')
  }

  async function handleGapStatus(gapId: string, status: 'dismissed' | 'open') {
    if (!detail) return
    const updated = await api.updateGapStatus(projectId, detail.document.id, gapId, status)
    setDetail(updated)
  }

  async function handleResolveGapAsStory(gapId: string, parentId: string, fields?: ItemFields) {
    if (!detail) return
    const previousDocId = detail.document.id
    const updated = await api.resolveGapAsStory(projectId, previousDocId, gapId, { parent_id: parentId, ...fields })
    applyUpdate(previousDocId, updated, 'resolving this gap')
  }

  async function handleApprove() {
    if (!detail) return
    await api.approve(projectId, detail.document.id)
    await load()
  }

  async function handlePublishConfluence() {
    if (!detail) return
    await api.publishToConfluence(projectId, detail.document.id)
    await load()
  }

  async function handleRunEvaluation() {
    if (!detail) return
    const updated = await api.runEvaluation(projectId, detail.document.id)
    setDetail(updated) // evaluation never forks a version — no applyUpdate needed
  }

  async function handleDeleteItem(itemId: string) {
    if (!detail) return
    const previousDocId = detail.document.id
    const updated = await api.deleteItem(projectId, previousDocId, itemId)
    applyUpdate(previousDocId, updated, 'deleting this item')
  }

  async function handleAcceptSuggestion(itemId: string) {
    if (!detail) return
    const previousDocId = detail.document.id
    const updated = await api.acceptSuggestion(projectId, previousDocId, itemId)
    applyUpdate(previousDocId, updated, 'accepting this suggestion')
  }

  async function handleDismissSuggestion(itemId: string) {
    if (!detail) return
    const previousDocId = detail.document.id
    const updated = await api.dismissSuggestion(projectId, previousDocId, itemId)
    applyUpdate(previousDocId, updated, 'dismissing this suggestion')
  }

  async function handleChangeRequestFiled(result: ChangeRequestIngestResponse) {
    if (!detail) return
    const previousDocId = detail.document.id
    const updated = await api.getRequirementsVersion(projectId, result.requirements_document.id)
    applyUpdate(previousDocId, updated, 'filing this change request')
  }

  if (detail === undefined) {
    return <div className="requirements-page__loading">Loading…</div>
  }

  if (error) {
    return (
      <div className="requirements-page">
        <Banner tone="danger">{error}</Banner>
      </div>
    )
  }

  if (detail === null) {
    return (
      <div className="requirements-page">
        <ResourceStagingPanel projectId={projectId} />
        <ClarifyingQuestionsPanel projectId={projectId} />
        <RunExtractionPanel projectId={projectId} onExtracted={handleExtracted} />
      </div>
    )
  }

  return (
    <div className="requirements-page">
      {forkNotice && <Banner tone="info">{forkNotice}</Banner>}

      {detail.document.approval_status === 'approved' && !forkNotice && (
        <Banner tone="info">
          This version is approved and locked. Editing an item will create a new draft version
          rather than changing what was approved.
        </Banner>
      )}

      <ApprovalHeader
        projectId={projectId}
        document={detail.document}
        unresolvedGapCount={detail.unresolved_gap_count}
        onApprove={handleApprove}
        onPublishConfluence={handlePublishConfluence}
      />

      <EvaluationPanel evaluation={detail.evaluation} onRun={handleRunEvaluation} />

      <ChangeRequestPanel projectId={projectId} onFiled={handleChangeRequestFiled} />

      <div className="requirements-page__layout">
        <div className="requirements-page__main">
          <EpicStoryTree
            projectId={projectId}
            docId={detail.document.id}
            epics={detail.epics}
            stories={detail.stories}
            onSaveItem={handleSaveItem}
            onCreateEpic={handleCreateEpic}
            onCreateStory={handleCreateStory}
            onDeleteItem={handleDeleteItem}
          />
        </div>
        <aside className="requirements-page__sidebar">
          <SuggestionsPanel
            suggestions={detail.suggestions}
            epics={detail.epics}
            onAccept={handleAcceptSuggestion}
            onDismiss={handleDismissSuggestion}
          />
          <GapPanel
            projectId={projectId}
            docId={detail.document.id}
            gaps={detail.gaps}
            epics={detail.epics}
            onSetStatus={handleGapStatus}
            onResolveAsStory={handleResolveGapAsStory}
          />
        </aside>
      </div>
    </div>
  )
}
