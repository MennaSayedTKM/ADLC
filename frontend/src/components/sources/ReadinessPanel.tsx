import type { GenerationState } from '../../state/ProjectContext'
import type { Readiness } from '../../lib/sources'
import { useElapsed } from '../../lib/useElapsed'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import { IndeterminateBar, ProgressBar } from '../ui/Progress'
import { Panel } from '../ui/Panel'
import './ReadinessPanel.css'

interface ReadinessPanelProps {
  readiness: Readiness
  generation: GenerationState
  onGenerate: () => void
  onDismissError: () => void
}

export function ReadinessPanel({ readiness, generation, onGenerate, onDismissError }: ReadinessPanelProps) {
  const running = generation.status === 'running'
  const elapsed = useElapsed(generation.status === 'running' ? generation.startedAt : null)

  return (
    <Panel
      title="Ready to generate?"
      tone="accent"
      actions={
        <span className="readiness__percent tabular" aria-label={`${readiness.percent} percent ready`}>
          {readiness.percent}%
        </span>
      }
    >
      <ProgressBar value={readiness.percent} label="Readiness to generate" />
      <p className="readiness__headline">{readiness.headline}</p>

      <ul className="readiness__checks">
        {readiness.checks.map((check) => (
          <li key={check.id} className="readiness__check">
            <Icon
              name={check.level === 'met' ? 'check-circle' : check.level === 'missing' ? 'x-circle' : 'alert'}
              size={19}
              className={`readiness__icon readiness__icon--${check.level}`}
            />
            <span>
              <span className="readiness__label">{check.label}</span>
              <span className="readiness__detail">{check.detail}</span>
            </span>
          </li>
        ))}
      </ul>

      {generation.status === 'failed' && (
        <Banner
          tone="danger"
          action={
            <Button size="sm" variant="secondary" onClick={onDismissError}>
              Dismiss
            </Button>
          }
        >
          <strong>We couldn’t generate your requirements.</strong> {generation.error}
          <br />
          Your sources are safe — try again in a moment.
        </Banner>
      )}

      {running ? (
        <div className="readiness__running" role="status" aria-live="polite">
          <IndeterminateBar label="Generating requirements" />
          <p>
            <strong>Reading your documents and drafting stories…</strong> {elapsed}
          </p>
          <p className="readiness__running-hint">
            This usually takes a couple of minutes. You can leave this page — we’ll keep working and tell you here when
            it’s done.
          </p>
        </div>
      ) : (
        <>
          <Button variant="primary" size="lg" icon="sparkles" disabled={!readiness.canGenerate} onClick={onGenerate} aria-describedby="generate-reason">
            {generation.status === 'failed' ? 'Try again' : 'Generate requirements'}
          </Button>
          <p id="generate-reason" className="readiness__caption">
            {readiness.canGenerate ? 'Takes about 2 minutes · you review everything before it’s final' : readiness.blockedReason}
          </p>
        </>
      )}
    </Panel>
  )
}
