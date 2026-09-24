import type { AlignmentReport, Document } from '../api/types'
import { Badge } from './ui/Badge'
import './DesignHeader.css'

interface DesignHeaderProps {
  document: Document
  requirementsVersion: number | null
  reports: AlignmentReport[]
}

export function DesignHeader({ document, requirementsVersion, reports }: DesignHeaderProps) {
  const aligned = reports.filter((r) => r.status === 'aligned').length
  const partial = reports.filter((r) => r.status === 'partial').length
  const misaligned = reports.filter((r) => r.status === 'misaligned').length

  return (
    <div className="design-header">
      <div className="design-header__meta">
        <h1 className="design-header__filename">{document.source_filename}</h1>
        <div className="design-header__badges">
          {requirementsVersion !== null && (
            <Badge tone="accent">checked against requirements v{requirementsVersion}</Badge>
          )}
          <Badge tone="neutral">{reports.length} screen{reports.length === 1 ? '' : 's'}</Badge>
        </div>
      </div>

      <div className="design-header__summary">
        {aligned > 0 && <Badge tone="success">{aligned} aligned</Badge>}
        {partial > 0 && <Badge tone="warning">{partial} partial</Badge>}
        {misaligned > 0 && <Badge tone="danger">{misaligned} misaligned</Badge>}
      </div>
    </div>
  )
}
