import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { RequirementsDetail } from '../../api/types'
import { diffStories, type StoryDiff } from '../../lib/stories'
import { Banner } from '../ui/Banner'
import { Badge } from '../ui/Badge'
import { Modal } from '../ui/Modal'
import './CompareDrawer.css'

interface CompareDrawerProps {
  open: boolean
  onClose: () => void
  projectId: string
  current: RequirementsDetail
}

export function CompareDrawer({ open, onClose, projectId, current }: CompareDrawerProps) {
  const [previous, setPrevious] = useState<RequirementsDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const previousId = current.document.previous_version_id

  useEffect(() => {
    if (!open || !previousId) return
    let cancelled = false
    setPrevious(null)
    setError(null)
    api
      .getRequirementsVersion(projectId, previousId)
      .then((detail) => !cancelled && setPrevious(detail))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load the previous version'))
    return () => {
      cancelled = true
    }
  }, [open, previousId, projectId])

  const diff: StoryDiff | null = previous ? diffStories(previous.stories, current.stories) : null
  const noChanges = diff && diff.added.length === 0 && diff.removed.length === 0 && diff.changed.length === 0

  return (
    <Modal
      open={open}
      onClose={onClose}
      variant="drawer"
      title={previous ? `Version ${previous.document.version} → ${current.document.version}` : 'Compare versions'}
      description="What changed in the stories since the previous version."
    >
      {error && <Banner tone="danger">{error}</Banner>}
      {!previous && !error && <p className="page-status">Loading the previous version…</p>}

      {diff && (
        <div className="compare">
          <div className="compare__chips">
            <Badge tone="success" icon="plus">{diff.added.length} added</Badge>
            <Badge tone="danger" icon="x">{diff.removed.length} removed</Badge>
            <Badge tone="warning" icon="edit">{diff.changed.length} changed</Badge>
            <Badge>{diff.unchangedCount} unchanged</Badge>
          </div>

          {noChanges && <p className="compare__none">The stories are identical in both versions.</p>}

          {diff.added.length > 0 && (
            <section>
              <h3 className="compare__heading">Added</h3>
              <ul className="compare__list">
                {diff.added.map((s) => (
                  <li key={s.id} className="compare__item compare__item--added">
                    <span className="compare__id">{s.external_id}</span> {s.text}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {diff.removed.length > 0 && (
            <section>
              <h3 className="compare__heading">Removed</h3>
              <ul className="compare__list">
                {diff.removed.map((s) => (
                  <li key={s.id} className="compare__item compare__item--removed">
                    <span className="compare__id">{s.external_id}</span> {s.text}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {diff.changed.length > 0 && (
            <section>
              <h3 className="compare__heading">Changed</h3>
              <ul className="compare__list">
                {diff.changed.map(({ before, after }) => {
                  const beforeAc = before.acceptance_criteria?.length ?? 0
                  const afterAc = after.acceptance_criteria?.length ?? 0
                  return (
                    <li key={after.id} className="compare__item compare__item--changed">
                      <p>
                        <span className="compare__id">{after.external_id}</span>
                        {before.text !== after.text ? (
                          <>
                            <del>{before.text}</del> → <strong>{after.text}</strong>
                          </>
                        ) : (
                          after.text
                        )}
                      </p>
                      {beforeAc !== afterAc && (
                        <p className="compare__detail">
                          Acceptance criteria: {beforeAc} → {afterAc}
                        </p>
                      )}
                      {before.description !== after.description && <p className="compare__detail">Description edited</p>}
                    </li>
                  )
                })}
              </ul>
            </section>
          )}
        </div>
      )}
    </Modal>
  )
}
