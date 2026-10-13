import type { AlignmentReport } from '../../api/types'
import './ScreenViewer.css'

interface ScreenViewerProps {
  report: AlignmentReport
  imageUrl: string
  activeFindingId: string | null
  onSelectFinding: (findingId: string) => void
}

/**
 * The screen with a numbered pin on each finding the checker could locate.
 * Findings about something missing have no region, so they get no pin — they
 * appear in the list only.
 */
export function ScreenViewer({ report, imageUrl, activeFindingId, onSelectFinding }: ScreenViewerProps) {
  const active = report.findings.find((f) => f.id === activeFindingId)?.bounding_box

  return (
    <figure className="viewer">
      <div className="viewer__frame">
        <img src={imageUrl} alt={`Screen ${report.page}`} className="viewer__image" />

        {active && (
          <div
            className="viewer__region"
            aria-hidden="true"
            style={{
              top: `${active.top}%`,
              left: `${active.left}%`,
              width: `${active.right - active.left}%`,
              height: `${active.bottom - active.top}%`,
            }}
          />
        )}

        {report.findings.map((finding, index) => {
          const box = finding.bounding_box
          if (!box) return null
          const closed = finding.resolution_status !== 'open'
          return (
            <button
              key={finding.id}
              type="button"
              className={`viewer__pin viewer__pin--${report.status} ${closed ? 'viewer__pin--closed' : ''} ${
                finding.id === activeFindingId ? 'viewer__pin--active' : ''
              }`}
              style={{ top: `${box.top}%`, left: `${box.right}%` }}
              onClick={() => onSelectFinding(finding.id)}
              aria-label={`Finding ${index + 1}${closed ? ` (${finding.resolution_status})` : ''}: ${finding.issue}`}
            >
              {index + 1}
            </button>
          )
        })}
      </div>
      <figcaption className="viewer__caption">Numbered pins match the findings on the right.</figcaption>
    </figure>
  )
}
