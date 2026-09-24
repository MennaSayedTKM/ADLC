import type { ReactNode } from 'react'
import './Banner.css'

type Tone = 'info' | 'warning' | 'danger'

export function Banner({ tone = 'info', children }: { tone?: Tone; children: ReactNode }) {
  return <div className={`banner banner--${tone}`}>{children}</div>
}
