import './Progress.css'

type Tone = 'accent' | 'success' | 'warning' | 'danger'

interface ProgressBarProps {
  value: number // 0–100
  tone?: Tone
  label: string
}

export function ProgressBar({ value, tone = 'accent', label }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div className="progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={clamped}>
      <div className={`progress__fill progress__fill--${tone}`} style={{ width: `${clamped}%` }} />
    </div>
  )
}

/** Indeterminate bar for work whose length we cannot know (no job-status endpoint yet). */
export function IndeterminateBar({ label }: { label: string }) {
  return (
    <div className="progress progress--indeterminate" role="progressbar" aria-label={label} aria-busy="true">
      <div className="progress__fill progress__fill--accent" />
    </div>
  )
}

interface StepSegmentsProps {
  states: ('done' | 'current' | 'upcoming')[]
  label: string
}

/** The segmented lifecycle strip used on project cards. */
export function StepSegments({ states, label }: StepSegmentsProps) {
  return (
    <div className="segments" role="img" aria-label={label}>
      {states.map((state, i) => (
        <span key={i} className={`segments__bar segments__bar--${state}`} />
      ))}
    </div>
  )
}

interface RingProps {
  value: number // 0–100
  size?: number
  tone?: Tone
  label: string
}

export function Ring({ value, size = 88, tone = 'success', label }: RingProps) {
  const stroke = 9
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div className="ring" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle className="ring__track" cx={size / 2} cy={size / 2} r={radius} strokeWidth={stroke} fill="none" />
        <circle
          className={`ring__value ring__value--${tone}`}
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped / 100)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span className="ring__label tabular">{clamped}%</span>
    </div>
  )
}
