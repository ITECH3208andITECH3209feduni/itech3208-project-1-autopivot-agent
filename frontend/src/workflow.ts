
import type { Step } from './components/primitives'

export const WORKFLOW_STEPS: Step[] = [
  { key: 'upload', label: 'Add vehicle' },
  { key: 'process', label: 'Process' },
  { key: 'review', label: 'Review' },
]

export type WorkflowStep = 'upload' | 'process' | 'review'

export function stepHref(step: WorkflowStep, listingId: number | null): string | null {
  if (step === 'upload') return '/app/upload'
  if (listingId === null) return null
  return step === 'process'
    ? `/app/processing/${listingId}`
    : `/app/vehicles/${listingId}`
}
