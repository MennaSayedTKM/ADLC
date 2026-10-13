import { useState } from 'react'
import type { AlignmentFinding, AlignmentStatus } from '../../api/types'
import { ALIGNMENT_LABEL } from '../../lib/design'
import { projectHref } from '../../lib/router'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import './FindingItem.css'

type Resolution = 'resolved' | 'dismissed' | 'open'

interface FindingItemProps {
  number: number
  projectId: string
  finding: AlignmentFinding
  screenStatus: AlignmentStatus
  active: boolean
  onSelect: () => void
  onSetStatus: (findingId: string, status: Resolution) => Promise<void>
}

const SCREEN_TONE = { aligned: 'success', partial: 'warning', misaligned: 'danger' } as const

export function FindingItem({ number, projectId, finding, screenStatus, active, onSelect, onSetStatus }: FindingItemProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const located = finding.bounding_box !== null
  const closed = finding.resolution_status !== 'open'

  async function set(status: Resolution) {
    setBusy(true)
    setError(null)
    try {
      await onSetStatus(finding.id, status)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update this finding')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className={`finding ${active ? 'finding--active' : ''} ${closed ? 'finding--closed' : ''}`}>
      <button
        type="button"
        className="finding__main"
        onClick={onSelect}
        aria-pressed={active}
        aria-label={`Finding ${number}: ${finding.issue}`}
        disabled={!located}
        title={located ? 'Show on the screen' : 'This issue has no location on the screen'}
      >
        <span className={`finding__number finding__number--${located ? screenStatus : 'none'}`} aria-hidden="true">
          {number}
        </span>
        <span className="finding__text">
          <span className="finding__tags">
            <Badge tone={SCREEN_TONE[screenStatus]} icon={screenStatus === 'aligned' ? 'check' : 'alert'}>
              {ALIGNMENT_LABEL[screenStatus]}
            </Badge>
            {finding.requirement_external_id && <Badge tone="accent">{finding.requirement_external_id}</Badge>}
            {!located && <span className="finding__no-region">No location — something is missing</span>}
          </span>
          <span className="finding__issue">{finding.issue}</span>
        </span>
      </button>

      <p className="finding__recommendation">
        <strong>Recommendation:</strong> {finding.recommendation}
      </p>

      {error && <p className="finding__error">{error}</p>}

      <div className="finding__actions">
        {finding.resolution_status === 'open' ? (
          <>
            <Button size="sm" variant="secondary" icon="check" loading={busy} onClick={() => set('resolved')}>
              Resolve
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => set('dismissed')}>
              Dismiss
            </Button>
          </>
        ) : (
          <>
            <span className="finding__state">
              <Icon name={finding.resolution_status === 'resolved' ? 'check-circle' : 'x-circle'} size={16} />
              {finding.resolution_status === 'resolved' ? 'Resolved' : 'Dismissed'}
            </span>
            <Button size="sm" variant="ghost" loading={busy} onClick={() => set('open')}>
              Reopen
            </Button>
          </>
        )}
        {finding.requirement_external_id && (
          <a className="link-button finding__story-link" href={projectHref(projectId, 'requirements', { story: finding.requirement_external_id })}>
            Open {finding.requirement_external_id}
          </a>
        )}
      </div>
    </li>
  )
}
