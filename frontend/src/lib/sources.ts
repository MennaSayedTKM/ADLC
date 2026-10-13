import type { ClarifyingQuestion, IntakeResource, IntakeResourceKind } from '../api/types'

/**
 * Task-language names for the source types (the API keeps its original keys).
 * Technical names stay available as tooltips.
 */
export const KIND_LABEL: Record<IntakeResourceKind, string> = {
  primary_requirements: 'Main requirements',
  meeting_notes: 'Meeting notes',
  policy_reference: 'Client policy',
  other: 'Other',
}

export const KIND_OPTIONS: IntakeResourceKind[] = ['primary_requirements', 'meeting_notes', 'policy_reference', 'other']

const POLICY_HINT = /polic|standard|complian|gdpr|security|regulat|guideline/i
const NOTES_HINT = /meeting|notes|minutes|workshop|whiteboard|transcript|call|interview/i
const IMAGE_EXT = /\.(png|jpe?g|webp|bmp|tiff?)$/i

/**
 * Best guess at what a file is, from its name and type alone. There is no
 * server-side classifier, so this is deliberately conservative: anything
 * unrecognised defaults to the main requirements document and the user can
 * change it.
 */
export function guessResourceKind(filename: string): IntakeResourceKind {
  if (POLICY_HINT.test(filename)) return 'policy_reference'
  if (NOTES_HINT.test(filename) || IMAGE_EXT.test(filename)) return 'meeting_notes'
  return 'primary_requirements'
}

export type ReadinessLevel = 'met' | 'missing' | 'optional'

export interface ReadinessCheck {
  id: 'main' | 'policy' | 'questions'
  label: string
  detail: string
  level: ReadinessLevel
  required: boolean
}

export interface Readiness {
  percent: number
  canGenerate: boolean
  blockedReason: string | null
  headline: string
  checks: ReadinessCheck[]
}

const WEIGHT = { main: 60, policy: 20, questions: 20 } as const

/**
 * "Ready to generate?" — one required input (a main requirements document) and
 * two recommended ones. The percentage is just these weights added up, so it is
 * always explainable from the checklist next to it.
 */
export function computeReadiness(
  resources: IntakeResource[],
  activeStandards: number,
  questions: ClarifyingQuestion[],
): Readiness {
  const usable = resources.filter((r) => !r.processing_error)
  const hasMain = usable.some((r) => r.resource_kind === 'primary_requirements')
  const hasPolicy = usable.some((r) => r.resource_kind === 'policy_reference')
  const pending = questions.filter((q) => q.status === 'pending').length
  const answered = questions.filter((q) => q.status === 'answered').length

  const checks: ReadinessCheck[] = [
    {
      id: 'main',
      label: hasMain ? 'Main requirements added' : 'Main requirements needed',
      detail: hasMain ? 'The document your stories are built from.' : 'Add at least one main requirements document.',
      level: hasMain ? 'met' : 'missing',
      required: true,
    },
    {
      id: 'policy',
      label: hasPolicy ? 'Client policy included' : 'No client policy yet',
      detail: hasPolicy
        ? 'Will be applied to every story.'
        : activeStandards > 0
          ? 'Company standards will be applied instead.'
          : 'Optional — add the client’s own rules if they have them.',
      level: hasPolicy || activeStandards > 0 ? 'met' : 'optional',
      required: false,
    },
    {
      id: 'questions',
      label:
        questions.length === 0
          ? 'No questions asked yet'
          : pending === 0
            ? 'Client questions answered'
            : `${pending} open ${pending === 1 ? 'question' : 'questions'}`,
      detail:
        questions.length === 0
          ? 'Optional — questions sharpen the first draft.'
          : pending === 0
            ? `${answered} answered.`
            : 'Optional — answers improve quality.',
      level: questions.length > 0 && pending === 0 ? 'met' : 'optional',
      required: false,
    },
  ]

  // The extras only add context to a main document, so they earn nothing without one.
  const percent = hasMain
    ? WEIGHT.main +
      (hasPolicy || activeStandards > 0 ? WEIGHT.policy : 0) +
      (questions.length > 0 && pending === 0 ? WEIGHT.questions : 0)
    : 0

  const headline = !hasMain
    ? 'Add your main requirements document to begin.'
    : percent >= 100
      ? 'Everything is in place.'
      : 'Good to go — a little more context would sharpen the result.'

  return {
    percent,
    canGenerate: hasMain,
    blockedReason: hasMain ? null : 'Add a main requirements document to continue.',
    headline,
    checks,
  }
}
