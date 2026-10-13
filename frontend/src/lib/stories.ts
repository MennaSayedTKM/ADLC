import type { RequirementItem } from '../api/types'

const TBD = /\[TBD[^\]]*\]/i

export type StoryStatus = 'ready' | 'needs_input'

/**
 * A story is "ready" when a person could start designing from it: it has at
 * least one acceptance criterion and nothing in it still says [TBD].
 */
export function storyStatus(story: RequirementItem): StoryStatus {
  const hasCriteria = (story.acceptance_criteria?.length ?? 0) > 0
  const texts = [
    ...(story.scenarios ?? []).flatMap((s) => [s.given, s.when, s.then]),
    ...(story.error_handling ?? []).map((e) => e.message),
  ]
  return hasCriteria && !texts.some((t) => TBD.test(t)) ? 'ready' : 'needs_input'
}

export const STORY_STATUS_LABEL: Record<StoryStatus, string> = {
  ready: 'Ready',
  needs_input: 'Needs input',
}

export interface StoryDiff {
  added: RequirementItem[]
  removed: RequirementItem[]
  changed: { before: RequirementItem; after: RequirementItem }[]
  unchangedCount: number
}

function fingerprint(item: RequirementItem): string {
  return JSON.stringify([
    item.text,
    item.description,
    item.acceptance_criteria,
    item.scenarios,
    item.error_handling,
  ])
}

/**
 * Compare two requirement versions story by story, matching on the story's
 * visible ID (US-01 …). Versions are forked copies, so IDs carry across.
 */
export function diffStories(previous: RequirementItem[], current: RequirementItem[]): StoryDiff {
  const before = new Map(previous.map((s) => [s.external_id, s]))
  const after = new Map(current.map((s) => [s.external_id, s]))

  const added = current.filter((s) => !before.has(s.external_id))
  const removed = previous.filter((s) => !after.has(s.external_id))
  const changed: StoryDiff['changed'] = []
  let unchangedCount = 0

  for (const story of current) {
    const old = before.get(story.external_id)
    if (!old) continue
    if (fingerprint(old) === fingerprint(story)) unchangedCount += 1
    else changed.push({ before: old, after: story })
  }

  return { added, removed, changed, unchangedCount }
}
