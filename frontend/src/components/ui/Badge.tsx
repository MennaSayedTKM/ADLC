import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'
import './Badge.css'

type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info'

interface BadgeProps {
  tone?: Tone
  /** Status is never conveyed by colour alone: pair the tone with an icon or a clear label. */
  icon?: IconName
  children: ReactNode
}

export function Badge({ tone = 'neutral', icon, children }: BadgeProps) {
  return (
    <span className={`badge badge--${tone}`}>
      {icon && <Icon name={icon} size={12} strokeWidth={2.2} />}
      {children}
    </span>
  )
}
