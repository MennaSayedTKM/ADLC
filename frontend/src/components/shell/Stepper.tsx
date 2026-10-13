import { projectHref } from '../../lib/router'
import type { LifecycleStep } from '../../lib/lifecycle'
import { Icon } from '../ui/Icon'
import './Stepper.css'

/**
 * The six-step lifecycle, shown on every project screen so the user always
 * knows where they are. Each step links to the page where that work happens.
 */
export function Stepper({ projectId, steps, loading = false }: { projectId: string; steps: LifecycleStep[]; loading?: boolean }) {
  const current = loading ? undefined : steps.find((s) => s.state === 'current')

  return (
    <nav className={`stepper ${loading ? 'stepper--loading' : ''}`} aria-label="Project progress" aria-busy={loading || undefined}>
      {current && (
        <p className="stepper__compact" aria-hidden="true">
          Step {current.number} of {steps.length} · <strong>{current.title}</strong>
        </p>
      )}
      <ol className="stepper__list">
        {steps.map((step, index) => (
          <li key={step.id} className={`stepper__item stepper__item--${loading ? 'upcoming' : step.state}`}>
            <a
              href={projectHref(projectId, step.page)}
              className="stepper__link"
              aria-current={step.state === 'current' ? 'step' : undefined}
            >
              <span className="stepper__bullet" aria-hidden="true">
                {!loading && step.state === 'done' ? <Icon name="check" size={15} strokeWidth={2.5} /> : step.number}
              </span>
              <span className="stepper__text">
                <span className="stepper__title">{step.title}</span>
                <span className="stepper__subtitle">{step.subtitle}</span>
              </span>
              {!loading && (
                <span className="sr-only">
                  {step.state === 'done' ? ' — done' : step.state === 'current' ? ' — current step' : ' — not started'}
                </span>
              )}
            </a>
            {index < steps.length - 1 && <span className="stepper__connector" aria-hidden="true" />}
          </li>
        ))}
      </ol>
    </nav>
  )
}
