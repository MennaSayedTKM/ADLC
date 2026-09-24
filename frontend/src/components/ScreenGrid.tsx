import type { AlignmentReport } from '../api/types'
import { Badge } from './ui/Badge'
import './ScreenGrid.css'

const STATUS_TONE = { aligned: 'success', partial: 'warning', misaligned: 'danger' } as const

interface ScreenGridProps {
  reports: AlignmentReport[]
  imageUrl: (page: number) => string
  onSelect: (page: number) => void
}

export function ScreenGrid({ reports, imageUrl, onSelect }: ScreenGridProps) {
  return (
    <div className="screen-grid">
      {reports.map((report) => {
        const openFindings = report.findings.filter((f) => f.resolution_status === 'open').length
        return (
          <button
            key={report.id}
            type="button"
            className="screen-card"
            onClick={() => onSelect(report.page)}
          >
            <div className="screen-card__thumb-wrap">
              <img src={imageUrl(report.page)} alt={`Screen ${report.page}`} className="screen-card__thumb" />
            </div>
            <div className="screen-card__footer">
              <span className="screen-card__page">Screen {report.page}</span>
              <Badge tone={STATUS_TONE[report.status]}>{report.status}</Badge>
            </div>
            {openFindings > 0 && (
              <span className="screen-card__finding-count">
                {openFindings} open finding{openFindings === 1 ? '' : 's'}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
