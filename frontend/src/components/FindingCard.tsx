import { useState } from 'react'
import type { AlignmentFinding } from '../api/types'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import './FindingCard.css'

interface FindingCardProps {
  finding: AlignmentFinding
  onSetStatus: (findingId: string, status: 'resolved' | 'dismissed' | 'open') => Promise<void>
  active: boolean
  onSelect: () => void
}

export function FindingCard({ finding, onSetStatus, active, onSelect }: FindingCardProps) {
  const [busy, setBusy] = useState(false)
  const hasRegion = finding.bounding_box !== null

  async function handle(status: 'resolved' | 'dismissed' | 'open') {
    setBusy(true)
    try {
      await onSetStatus(finding.id, status)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li
      className={`finding-card finding-card--${finding.resolution_status} ${active ? 'finding-card--active' : ''} ${hasRegion ? 'finding-card--clickable' : ''}`}
      onClick={hasRegion ? onSelect : undefined}
    >
      <div className="finding-card__top">
        {finding.requirement_external_id && <Badge tone="accent">{finding.requirement_external_id}</Badge>}
        {hasRegion && (
          <span className="finding-card__region-hint">{active ? '● shown on screen' : '○ show on screen'}</span>
        )}
      </div>
      <p className="finding-card__issue">{finding.issue}</p>
      <p className="finding-card__recommendation">
        <span className="finding-card__recommendation-label">Recommendation:</span> {finding.recommendation}
      </p>
      <div className="finding-card__actions" onClick={(e) => e.stopPropagation()}>
        {finding.resolution_status === 'open' && (
          <>
            <Button variant="secondary" size="sm" onClick={() => handle('resolved')} disabled={busy}>
              Resolve
            </Button>
            <Button variant="ghost" size="sm" onClick={() => handle('dismissed')} disabled={busy}>
              Dismiss
            </Button>
          </>
        )}
        {finding.resolution_status === 'resolved' && (
          <>
            <span className="finding-card__status-label finding-card__status-label--resolved">✓ Resolved</span>
            <Button variant="ghost" size="sm" onClick={() => handle('open')} disabled={busy}>
              Reopen
            </Button>
          </>
        )}
        {finding.resolution_status === 'dismissed' && (
          <>
            <span className="finding-card__status-label">Dismissed</span>
            <Button variant="ghost" size="sm" onClick={() => handle('open')} disabled={busy}>
              Reopen
            </Button>
          </>
        )}
      </div>
    </li>
  )
}
