import type { ElementType, ReactNode } from 'react'
import './Panel.css'

interface PanelProps {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  /** Visual weight: `accent` for the one hero card on a page, `plain` for everything else. */
  tone?: 'plain' | 'accent' | 'sunken'
  as?: ElementType
  className?: string
  children?: ReactNode
}

/** The standard content container: a titled card with an optional action slot. */
export function Panel({ title, description, actions, tone = 'plain', as: Tag = 'section', className = '', children }: PanelProps) {
  return (
    <Tag className={`panel panel--${tone} ${className}`.trim()}>
      {(title || actions) && (
        <header className="panel__header">
          <div className="panel__heading">
            {title && <h2 className="panel__title">{title}</h2>}
            {description && <p className="panel__description">{description}</p>}
          </div>
          {actions && <div className="panel__actions">{actions}</div>}
        </header>
      )}
      {children}
    </Tag>
  )
}
