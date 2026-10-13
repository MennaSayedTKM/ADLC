import type { AlignmentFinding, AlignmentReport, AlignmentStatus } from '../api/types'

export const ALIGNMENT_LABEL: Record<AlignmentStatus, string> = {
  aligned: 'Aligned',
  partial: 'Partial',
  misaligned: 'Gap',
}

export interface AlignmentSummary {
  total: number
  aligned: number
  partial: number
  misaligned: number
  /** Whole-number percentage: aligned screens count fully, partial screens count half. */
  percent: number
  verdict: string
}

export function summarizeAlignment(reports: AlignmentReport[]): AlignmentSummary {
  const total = reports.length
  const aligned = reports.filter((r) => r.status === 'aligned').length
  const partial = reports.filter((r) => r.status === 'partial').length
  const misaligned = reports.filter((r) => r.status === 'misaligned').length
  const percent = total === 0 ? 0 : Math.round(((aligned + partial * 0.5) / total) * 100)

  const verdict =
    percent >= 90 ? 'Well aligned' : percent >= 70 ? 'Mostly aligned' : percent >= 40 ? 'Needs work' : 'Far from the requirements'

  return { total, aligned, partial, misaligned, percent, verdict }
}

export function openFindings(report: AlignmentReport): AlignmentFinding[] {
  return report.findings.filter((f) => f.resolution_status === 'open')
}

/** Distinct stories that at least one screen's findings point at. */
export function storiesTouchedByDesign(reports: AlignmentReport[]): Set<string> {
  const ids = new Set<string>()
  for (const report of reports) {
    for (const finding of report.findings) {
      if (finding.requirement_external_id) ids.add(finding.requirement_external_id)
    }
  }
  return ids
}
