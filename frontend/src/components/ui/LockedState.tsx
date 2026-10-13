import { Icon, type IconName } from './Icon'
import { ButtonLink } from './Button'
import './LockedState.css'

export interface ChecklistItem {
  label: string
  done: boolean
}

interface LockedStateProps {
  icon: IconName
  title: string
  body: string
  checklist: ChecklistItem[]
  ctaLabel: string
  ctaHref: string
}

/**
 * Replaces a dead-end "approve a version first" message: it says what is
 * missing, shows progress, and puts one button on the step that unblocks it.
 */
export function LockedState({ icon, title, body, checklist, ctaLabel, ctaHref }: LockedStateProps) {
  return (
    <section className="locked">
      <div className="locked__icon" aria-hidden="true">
        <Icon name={icon} size={30} />
      </div>
      <h2 className="locked__title">{title}</h2>
      <p className="locked__body">{body}</p>

      <ul className="locked__list">
        {checklist.map((item) => (
          <li key={item.label} className={`locked__item ${item.done ? 'locked__item--done' : ''}`}>
            <Icon name={item.done ? 'check' : 'clock'} size={17} strokeWidth={item.done ? 2.4 : 1.75} />
            <span className="locked__label">{item.label}</span>
            <span className="sr-only">{item.done ? '(done)' : '(still to do)'}</span>
          </li>
        ))}
      </ul>

      <ButtonLink variant="primary" size="lg" href={ctaHref}>
        {ctaLabel}
      </ButtonLink>
    </section>
  )
}
