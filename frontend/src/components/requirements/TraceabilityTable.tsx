import { useMemo, useState } from 'react'
import type { DesignDetail, RequirementsDetail } from '../../api/types'
import { ALIGNMENT_LABEL } from '../../lib/design'
import { downloadTextFile, plural, toCsv } from '../../lib/format'
import { storyStatus, STORY_STATUS_LABEL } from '../../lib/stories'
import { projectHref } from '../../lib/router'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import './TraceabilityTable.css'

interface TraceabilityTableProps {
  projectId: string
  detail: RequirementsDetail
  design: DesignDetail | null
}

interface Row {
  storyId: string
  title: string
  epic: string
  source: string
  status: ReturnType<typeof storyStatus>
  screens: { page: number; status: 'aligned' | 'partial' | 'misaligned'; issue: string }[]
}

/**
 * Source → story → design. The design column shows where a screen was flagged
 * against the story: the checker only reports problems, so an empty cell means
 * "no finding", not "proven covered".
 */
export function TraceabilityTable({ projectId, detail, design }: TraceabilityTableProps) {
  const [epicFilter, setEpicFilter] = useState('all')
  const [query, setQuery] = useState('')

  const rows = useMemo<Row[]>(() => {
    return detail.stories.map((story) => {
      const epic = detail.epics.find((e) => e.id === story.parent_id)
      const screens =
        design?.reports.flatMap((report) =>
          report.findings
            .filter((f) => f.requirement_external_id === story.external_id)
            .map((f) => ({ page: report.page, status: report.status, issue: f.issue })),
        ) ?? []
      return {
        storyId: story.external_id,
        title: story.text,
        epic: epic ? `${epic.external_id} · ${epic.text}` : '—',
        source: epic?.source_reference ? `${detail.document.source_filename} · §${epic.source_reference}` : detail.document.source_filename,
        status: storyStatus(story),
        screens,
      }
    })
  }, [detail, design])

  const visible = rows.filter((row) => {
    if (epicFilter !== 'all' && !row.epic.startsWith(`${epicFilter} ·`)) return false
    const q = query.trim().toLowerCase()
    return !q || row.title.toLowerCase().includes(q) || row.storyId.toLowerCase().includes(q)
  })

  function exportCsv() {
    const header = ['Story', 'Title', 'Epic', 'Source', 'Status', 'Design findings']
    const body = visible.map((r) => [
      r.storyId,
      r.title,
      r.epic,
      r.source,
      STORY_STATUS_LABEL[r.status],
      r.screens.map((s) => `Screen ${s.page}: ${s.issue}`).join(' | '),
    ])
    downloadTextFile(`traceability-${detail.document.version}.csv`, toCsv([header, ...body]))
  }

  return (
    <div className="trace">
      <div className="trace__toolbar">
        <label className="trace__search">
          <Icon name="search" size={16} />
          <span className="sr-only">Filter stories</span>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by story…" />
        </label>
        <label className="trace__select">
          <span className="sr-only">Epic</span>
          <select value={epicFilter} onChange={(e) => setEpicFilter(e.target.value)}>
            <option value="all">All epics</option>
            {detail.epics.map((e) => (
              <option key={e.id} value={e.external_id}>
                {e.external_id} · {e.text}
              </option>
            ))}
          </select>
        </label>
        <span className="trace__count">{plural(visible.length, 'story', 'stories')}</span>
        <Button variant="secondary" size="sm" icon="download" onClick={exportCsv}>
          Export CSV
        </Button>
      </div>

      <div className="scroll-x trace__table-wrap">
        <table className="trace__table">
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Story</th>
              <th scope="col">Status</th>
              <th scope="col">{design ? 'Design findings' : 'Design'}</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.storyId}>
                <td className="trace__source">{row.source}</td>
                <td>
                  <a className="trace__story" href={projectHref(projectId, 'requirements', { story: row.storyId })}>
                    <span className="trace__id">{row.storyId}</span> {row.title}
                  </a>
                  <span className="trace__epic">{row.epic}</span>
                </td>
                <td>
                  <Badge tone={row.status === 'ready' ? 'success' : 'warning'} icon={row.status === 'ready' ? 'check' : 'alert'}>
                    {STORY_STATUS_LABEL[row.status]}
                  </Badge>
                </td>
                <td>
                  {!design ? (
                    <span className="trace__none">Not checked yet</span>
                  ) : row.screens.length === 0 ? (
                    <span className="trace__none">No findings</span>
                  ) : (
                    <ul className="trace__screens">
                      {row.screens.map((s, i) => (
                        <li key={i}>
                          <a href={projectHref(projectId, 'validate', { screen: String(s.page) })}>
                            <Badge tone={s.status === 'aligned' ? 'success' : s.status === 'partial' ? 'warning' : 'danger'}>
                              Screen {s.page} · {ALIGNMENT_LABEL[s.status]}
                            </Badge>
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={4} className="trace__none">
                  No stories match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
