import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react'
import { Icon, type IconName } from './Icon'
import './Button.css'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

interface CommonProps {
  variant?: Variant
  size?: Size
  icon?: IconName
  /** Icon after the label (e.g. an arrow on a "next" action). */
  iconAfter?: IconName
  children: ReactNode
}

function classes(variant: Variant, size: Size, className: string) {
  return `btn btn--${variant} btn--${size} ${className}`.trim()
}

type ButtonProps = CommonProps & ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }

export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  iconAfter,
  loading = false,
  className = '',
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={classes(variant, size, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className="btn__spinner" aria-hidden="true" /> : icon && <Icon name={icon} size={size === 'sm' ? 15 : 17} />}
      {children}
      {iconAfter && !loading && <Icon name={iconAfter} size={size === 'sm' ? 15 : 17} />}
    </button>
  )
}

type ButtonLinkProps = CommonProps & AnchorHTMLAttributes<HTMLAnchorElement>

/** A link that looks like a button — for navigation and downloads. */
export function ButtonLink({
  variant = 'secondary',
  size = 'md',
  icon,
  iconAfter,
  className = '',
  children,
  ...rest
}: ButtonLinkProps) {
  return (
    <a className={classes(variant, size, className)} {...rest}>
      {icon && <Icon name={icon} size={size === 'sm' ? 15 : 17} />}
      {children}
      {iconAfter && <Icon name={iconAfter} size={size === 'sm' ? 15 : 17} />}
    </a>
  )
}
