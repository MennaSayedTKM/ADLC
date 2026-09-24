import { useState } from 'react'
import { api } from '../api/client'
import type { ConfluencePublishInfo, Document } from '../api/types'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import './ApprovalHeader.css'

const STATUS_TONE = {
  draft: 'neutral',
  in_review: 'warning',
  approved: 'success',
} as const

const STATUS_LABEL = {
  draft: 'Draft',
  in_review: 'In review',
  approved: 'Approved',
} as const

interface ApprovalHeaderProps {
  projectId: string
  document: Document
  unresolvedGapCount: number
  onApprove: () => Promise<void>
  onPublishConfluence: () => Promise<void>
}

export function ApprovalHeader({
  projectId,
  document,
  unresolvedGapCount,
  onApprove,
  onPublishConfluence,
}: ApprovalHeaderProps) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [publishError, setPublishError] = useState<string | null>(null)

  const isApproved = document.approval_status === 'approved'
  const hasUnresolvedGaps = unresolvedGapCount > 0
  const confluence = document.type_metadata?.confluence as ConfluencePublishInfo | undefined

  async function handlePublishClick() {
    setPublishing(true)
    setPublishError(null)
    try {
      await onPublishConfluence()
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : 'Could not publish to Confluence')
    } finally {
      setPublishing(false)
    }
  }

  async function handleApproveClick() {
    if (hasUnresolvedGaps && !confirming) {
      setConfirming(true)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onApprove()
      setConfirming(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not approve')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="approval-header">
      <div className="approval-header__meta">
        <h1 className="approval-header__filename">{document.source_filename}</h1>
        <div className="approval-header__badges">
          <Badge tone="accent">v{document.version}</Badge>
          <Badge tone={STATUS_TONE[document.approval_status]}>
            {STATUS_LABEL[document.approval_status]}
          </Badge>
          {hasUnresolvedGaps && (
            <Badge tone="warning">
              {unresolvedGapCount} unresolved gap{unresolvedGapCount === 1 ? '' : 's'}
            </Badge>
          )}
        </div>
      </div>

      <div className="approval-header__actions">
        {error && <span className="approval-header__error">{error}</span>}
        {publishError && <span className="approval-header__error">{publishError}</span>}

        {isApproved ? (
          <>
            <Button variant="secondary" size="md" disabled>
              Approved
            </Button>
            <a
              className="btn btn--primary btn--md"
              href={api.exportPdfUrl(projectId, document.id, 'business')}
              title="Business requirements document for stakeholder review and sign-off"
              download
            >
              Export PDF
            </a>
            <a
              className="btn btn--ghost btn--md"
              href={api.exportPdfUrl(projectId, document.id, 'delivery')}
              title="Stories with scenarios and error handling, for the delivery team"
              download
            >
              Delivery PDF
            </a>
            {confluence ? (
              <a
                className="btn btn--secondary btn--md"
                href={confluence.page_url}
                target="_blank"
                rel="noreferrer"
              >
                View on Confluence ↗
              </a>
            ) : (
              <Button variant="secondary" size="md" onClick={handlePublishClick} disabled={publishing}>
                {publishing ? 'Publishing…' : 'Publish to Confluence'}
              </Button>
            )}
          </>
        ) : confirming ? (
          <div className="approval-header__confirm">
            <span>Approve with {unresolvedGapCount} open gap{unresolvedGapCount === 1 ? '' : 's'}?</span>
            <Button variant="primary" size="sm" onClick={handleApproveClick} disabled={busy}>
              Yes, approve
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirming(false)}
              disabled={busy}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <Button variant="primary" size="md" onClick={handleApproveClick} disabled={busy}>
            {busy ? 'Approving…' : 'Approve'}
          </Button>
        )}
      </div>
    </div>
  )
}
