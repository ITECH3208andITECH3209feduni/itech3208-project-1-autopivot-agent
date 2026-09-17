// The one journey through the product, named in one place.
//
// Upload, Processing and Results are three routes but a single task: get a
// dealer's photographs onto a backdrop. Each screen renders the same Stepper,
// so the steps have to be defined here rather than three times over —
// otherwise they drift and the labels stop agreeing with each other.

import type { Step } from './components/primitives'

export const WORKFLOW_STEPS: Step[] = [
  { key: 'upload', label: 'Add vehicle' },
  { key: 'process', label: 'Process' },
  { key: 'review', label: 'Review' },
]

export type WorkflowStep = 'upload' | 'process' | 'review'

/**
 * Where a step leads, given the listing it belongs to.
 *
 * Returns null when a step has nowhere to go yet: before a listing exists
 * there is no Processing screen to visit, and the Stepper renders it as
 * unreachable rather than as a link that lands on an empty page.
 */
export function stepHref(step: WorkflowStep, listingId: number | null): string | null {
  if (step === 'upload') return '/app/upload'
  if (listingId === null) return null
  return step === 'process'
    ? `/app/processing/${listingId}`
    : `/app/vehicles/${listingId}`
}
