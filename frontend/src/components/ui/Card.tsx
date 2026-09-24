import type { HTMLAttributes, ReactNode } from 'react'
import './Card.css'

export function Card({
  children,
  className = '',
  ...rest
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div className={`card ${className}`} {...rest}>
      {children}
    </div>
  )
}
