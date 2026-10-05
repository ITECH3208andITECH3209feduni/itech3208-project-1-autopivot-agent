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
 * The upload form aimed at a vehicle that already exists.
 *
 * Plain /app/upload always starts a new vehicle, so every "add photographs"
 * on an existing one used to open a blank form — and re-typing the details
 * into it made a duplicate listing. UploadView reads the `listing` parameter
 * written here.
 */
export function addPhotographsHref(listingId: number): string {
  return `/app/upload?listing=${listingId}`
}

/**
 * Where a step leads, given the listing it belongs to.
 *
 * Returns null when a step has nowhere to go yet: before a listing exists
 * there is no Processing screen to visit, and the Stepper renders it as
 * unreachable rather than as a link that lands on an empty page. Once one
 * does exist, stepping back to the first step means adding to it, not
 * starting again.
 */
export function stepHref(step: WorkflowStep, listingId: number | null): string | null {
  if (step === 'upload') return listingId === null ? '/app/upload' : addPhotographsHref(listingId)
  if (listingId === null) return null
  return step === 'process'
    ? `/app/processing/${listingId}`
    : `/app/vehicles/${listingId}`
}
