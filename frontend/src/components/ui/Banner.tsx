import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'
import './Banner.css'

type Tone = 'info' | 'warning' | 'danger' | 'success'

const TONE_ICON: Record<Tone, IconName> = {
  info: 'info',
  warning: 'alert',
  danger: 'alert',
  success: 'check-circle',
}

export function Banner({
  tone = 'info',
  children,
  action,
}: {
  tone?: Tone
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className={`banner banner--${tone}`} role={tone === 'danger' ? 'alert' : undefined}>
      <Icon name={TONE_ICON[tone]} size={18} className="banner__icon" />
      <div className="banner__body">{children}</div>
      {action && <div className="banner__action">{action}</div>}
    </div>
  )
}
