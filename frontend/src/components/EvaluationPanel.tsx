import { useState } from 'react'
import type { EvaluationFinding, EvaluationFindingCategory, EvaluationReport } from '../api/types'
import { Button } from './ui/Button'
import './EvaluationPanel.css'

interface EvaluationPanelProps {
  evaluation: EvaluationReport | null
  onRun: () => Promise<void>
}

type Tone = 'success' | 'warning' | 'danger'

function scoreTone(score: number): Tone {
  if (score >= 75) return 'success'
  if (score >= 50) return 'warning'
  return 'danger'
}

const CATEGORIES: { key: EvaluationFindingCategory; scoreOf: (e: EvaluationReport) => number }[] = [
  { key: 'Source material', scoreOf: (e) => e.source_material_score },
  { key: 'Stories', scoreOf: (e) => e.stories_score },
  { key: 'Advisory content', scoreOf: (e) => e.advisory_content_score },
]

export function EvaluationPanel({ evaluation, onRun }: EvaluationPanelProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleRun() {
    setBusy(true)
    setError(null)
    try {
      await onRun()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not run evaluation')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="evaluation-panel">
      <div className="evaluation-panel__header">
        <h2 className="evaluation-panel__title">Evaluation</h2>
        <Button variant="secondary" size="sm" onClick={handleRun} disabled={busy}>
          {busy ? 'Evaluating…' : evaluation ? 'Re-run evaluation' : 'Run evaluation'}
        </Button>
      </div>

      {error && <div className="evaluation-panel__error">{error}</div>}

      {!evaluation && !error && (
        <p className="evaluation-panel__empty">
          Not evaluated yet — run an evaluation to score the AI's output and the clarity of the
          client's source material.
        </p>
      )}

      {evaluation && (
        <>
          <div className="evaluation-panel__scores">
            <ScoreCard
              label="Output Quality"
              hint="How good is what's in the tree right now"
              score={evaluation.output_quality_score}
              summary={evaluation.output_summary}
            />
            <ScoreCard
              label="Input Quality"
              hint="How clear was the client's own material"
              score={evaluation.input_quality_score}
              summary={evaluation.input_summary}
            />
          </div>

          <div className="evaluation-panel__section">
            <h3 className="evaluation-panel__section-title">Key findings</h3>
            <div className="category-sections">
              {CATEGORIES.map(({ key, scoreOf }) => (
                <CategorySection
                  key={key}
                  category={key}
                  score={scoreOf(evaluation)}
                  findings={evaluation.key_findings.filter((f) => f.category === key)}
                />
              ))}
            </div>
          </div>

          {evaluation.recommendations.length > 0 && (
            <div className="evaluation-panel__section">
              <h3 className="evaluation-panel__section-title">Recommendations</h3>
              <div className="evaluation-panel__cards">
                {evaluation.recommendations.map((r, i) => (
                  <div key={i} className="recommendation-card">
                    {r}
                  </div>
                ))}
              </div>
            </div>
          )}

          <p className="evaluation-panel__meta">Last run {new Date(evaluation.updated_at).toLocaleString()}</p>
        </>
      )}
    </div>
  )
}

function ScoreCard({
  label,
  hint,
  score,
  summary,
}: {
  label: string
  hint: string
  score: number
  summary: string
}) {
  return (
    <div className="score-card">
      <ScoreRing score={score} />
      <div className="score-card__body">
        <span className="score-card__label">{label}</span>
        <span className="score-card__hint">{hint}</span>
        <p className="score-card__summary">{summary}</p>
      </div>
    </div>
  )
}

function ScoreRing({ score, size = 76, strokeWidth = 8 }: { score: number; size?: number; strokeWidth?: number }) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, score))
  const offset = circumference * (1 - clamped / 100)
  const tone = scoreTone(clamped)

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={`score-ring score-ring--${tone}`}>
      <circle cx={size / 2} cy={size / 2} r={radius} className="score-ring__track" strokeWidth={strokeWidth} fill="none" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        className="score-ring__value"
        strokeWidth={strokeWidth}
        fill="none"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" className="score-ring__text">
        {clamped}
      </text>
    </svg>
  )
}

function CategorySection({
  category,
  score,
  findings,
}: {
  category: EvaluationFindingCategory
  score: number
  findings: EvaluationFinding[]
}) {
  const tone = scoreTone(score)
  return (
    <div className="category-section">
      <div className="category-section__header">
        <span className="category-section__name">{category}</span>
        <ScoreBar score={score} tone={tone} />
      </div>
      {findings.length > 0 ? (
        <div className={`finding-carousel finding-carousel--${tone}`}>
          {findings.map((f, i) => (
            <div key={i} className={`finding-card finding-card--${tone}`}>
              <p className="finding-card__text">{f.text}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="category-section__empty">Nothing flagged here.</p>
      )}
    </div>
  )
}

function ScoreBar({ score, tone }: { score: number; tone: Tone }) {
  const clamped = Math.max(0, Math.min(100, score))
  return (
    <div className="score-bar">
      <div className="score-bar__track">
        <div className={`score-bar__fill score-bar__fill--${tone}`} style={{ width: `${clamped}%` }} />
      </div>
      <span className="score-bar__value">{clamped}/100</span>
    </div>
  )
}
