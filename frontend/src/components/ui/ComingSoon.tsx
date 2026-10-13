import './ComingSoon.css'

/** Marks a deliberately non-functional placeholder, so nothing pretends to work. */
export function ComingSoon({ label = 'Soon' }: { label?: string }) {
  return <span className="coming-soon">{label}</span>
}
