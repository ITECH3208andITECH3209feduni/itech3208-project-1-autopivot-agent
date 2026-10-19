// kept_without_processing is a permanent, per-image opt-out of the pipeline —
// it must beat the classifier's own verdict in isExcluded, since that verdict
// is left on the record rather than overwritten (see the include endpoint's
// "keep_only" mode). This is the direct unit proof; ResultsView's render test
// covers the same rule at the gallery level.

import { describe, expect, it } from 'vitest'

import { photograph } from '../test/helpers'
import { isExcluded } from './ListingImageKind'

describe('isExcluded', () => {
  it('is false for an exterior photograph', () => {
    expect(isExcluded(photograph({ image_kind: 'exterior' }))).toBe(false)
  })

  it('is false for a photograph the classifier has not reached yet', () => {
    expect(isExcluded(photograph({ image_kind: null }))).toBe(false)
  })

  it('is true for a non-exterior photograph by default', () => {
    expect(isExcluded(photograph({ image_kind: 'interior' }))).toBe(true)
  })

  it('is true for a non-exterior photograph explicitly not kept-without-processing', () => {
    expect(isExcluded(photograph({ image_kind: 'interior', kept_without_processing: false }))).toBe(true)
  })

  it('is false for a non-exterior photograph kept without processing', () => {
    expect(isExcluded(photograph({ image_kind: 'interior', kept_without_processing: true }))).toBe(false)
  })

  it('is false for an advertisement kept without processing', () => {
    expect(isExcluded(photograph({ image_kind: 'advertisement', kept_without_processing: true }))).toBe(false)
  })
})
