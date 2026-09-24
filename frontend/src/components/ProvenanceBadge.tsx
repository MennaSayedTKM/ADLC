import type { ItemOrigin } from '../api/types'
import { Badge } from './ui/Badge'

const LABELS: Partial<Record<ItemOrigin, string>> = {
  pm_manual: 'PM-authored',
  pm_ai_assisted: 'AI-assisted',
  ai_suggestion: 'AI suggestion',
}

/** Nothing rendered for 'extracted' — that's the expected default, not worth calling out. */
export function ProvenanceBadge({ origin }: { origin: ItemOrigin }) {
  const label = LABELS[origin]
  if (!label) return null
  return (
    <span title="How this item was added">
      <Badge tone={origin === 'pm_manual' ? 'neutral' : 'accent'}>{label}</Badge>
    </span>
  )
}
