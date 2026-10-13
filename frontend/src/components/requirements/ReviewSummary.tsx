import type { RequirementsDetail } from '../../api/types'
import { storyStatus } from '../../lib/stories'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { ProgressBar } from '../ui/Progress'
import './ReviewSummary.css'

interface ReviewSummaryProps {
  detail: RequirementsDetail
  approved: boolean
  onOpenQuality: () => void
  onOpenGaps: () => void
}

function scoreTone(score: number): 'success' | 'warning' | 'danger' {
  return score >= 75 ? 'success' : score >= 50 ? 'warning' : 'danger'
}

/** Three tiles that answer "can I approve this?" at a glance. */
export function ReviewSummary({ detail, approved, onOpenQuality, onOpenGaps }: ReviewSummaryProps) {
  const { stories, evaluation, unresolved_gap_count: gaps } = detail
  const ready = stories.filter((s) => storyStatus(s) === 'ready').length
  const readyPercent = stories.length === 0 ? 0 : Math.round((ready / stories.length) * 100)

  return (
    <div className="review-summary">
      <div className="summary-tile">
        <p className="summary-tile__label">Story quality</p>
        {evaluation ? (
          <>
            <p className="summary-tile__value tabular">{evaluation.output_quality_score}%</p>
            <ProgressBar value={evaluation.output_quality_score} tone={scoreTone(evaluation.output_quality_score)} label="Story quality score" />
            <button type="button" className="link-button" onClick={onOpenQuality}>
              See the full check
            </button>
          </>
        ) : (
          <>
            <p className="summary-tile__value summary-tile__value--muted">Not checked</p>
            <p className="summary-tile__hint">Score clarity and completeness before you approve.</p>
            <div>
              <Button size="sm" variant="secondary" icon="sparkles" onClick={onOpenQuality}>
                Run quality check
              </Button>
            </div>
          </>
        )}
      </div>

      <div className="summary-tile">
        <p className="summary-tile__label">Stories ready</p>
        <p className="summary-tile__value tabular">
          {ready} <span className="summary-tile__of">/ {stories.length}</span>
        </p>
        <ProgressBar value={readyPercent} label="Stories ready" />
        <p className="summary-tile__hint">Ready = has acceptance criteria and nothing left to fill in.</p>
      </div>

      <div className="summary-tile">
        <p className="summary-tile__label">Open gaps</p>
        <p className="summary-tile__value tabular">{gaps}</p>
        {gaps > 0 ? (
          <div className="summary-tile__row">
            {!approved && <Badge tone="warning" icon="alert">Resolve to approve</Badge>}
            <button type="button" className="link-button" onClick={onOpenGaps}>
              Review gaps
            </button>
          </div>
        ) : (
          <Badge tone="success" icon="check">Nothing blocking</Badge>
        )}
      </div>
    </div>
  )
}
