import { useState } from 'react'
import type { AlignmentReport } from '../api/types'
import { Badge } from './ui/Badge'
import { FindingCard } from './FindingCard'
import './ScreenDetail.css'

const STATUS_TONE = { aligned: 'success', partial: 'warning', misaligned: 'danger' } as const

interface ScreenDetailProps {
  report: AlignmentReport
  imageUrl: string
  onBack: () => void
  onSetFindingStatus: (findingId: string, status: 'resolved' | 'dismissed' | 'open') => Promise<void>
}

export function ScreenDetail({ report, imageUrl, onBack, onSetFindingStatus }: ScreenDetailProps) {
  const [activeFindingId, setActiveFindingId] = useState<string | null>(null)
  const activeFinding = report.findings.find((f) => f.id === activeFindingId)
  const box = activeFinding?.bounding_box

  return (
    <div className="screen-detail">
      <button type="button" className="screen-detail__back" onClick={onBack}>
        ← All screens
      </button>

      <div className="screen-detail__layout">
        <div className="screen-detail__image-wrap">
          <img src={imageUrl} alt={`Screen ${report.page}`} className="screen-detail__image" />
          {box && (
            <div
              className="screen-detail__highlight"
              style={{
                top: `${box.top}%`,
                left: `${box.left}%`,
                width: `${box.right - box.left}%`,
                height: `${box.bottom - box.top}%`,
              }}
            />
          )}
        </div>

        <div className="screen-detail__panel">
          <div className="screen-detail__panel-header">
            <h2 className="screen-detail__title">Screen {report.page}</h2>
            <Badge tone={STATUS_TONE[report.status]}>{report.status}</Badge>
          </div>

          {report.findings.length === 0 ? (
            <p className="screen-detail__empty">No findings — this screen fully satisfies the requirements it's relevant to.</p>
          ) : (
            <ul className="screen-detail__findings">
              {report.findings.map((finding) => (
                <FindingCard
                  key={finding.id}
                  finding={finding}
                  onSetStatus={onSetFindingStatus}
                  active={finding.id === activeFindingId}
                  onSelect={() => setActiveFindingId((prev) => (prev === finding.id ? null : finding.id))}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
