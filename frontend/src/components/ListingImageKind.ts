
import type { ImageKind, ListingImage } from '../api/client'

export type KindDescription = {
  label: string
  reason: string
}

const DESCRIPTIONS: Record<ImageKind, KindDescription> = {
  exterior: {
    label: 'Exterior',
    reason: 'A photograph of the vehicle itself, so it goes onto the backdrop.',
  },
  interior: {
    label: 'Interior',
    reason: 'Shot from inside the cabin — there is no exterior here to cut out.',
  },
  detail: {
    label: 'Detail',
    reason: 'A close-up of one part rather than the whole vehicle.',
  },
  advertisement: {
    label: 'Advertisement',
    reason: 'A banner or dealer badge that came in with the import, not a photograph of this car.',
  },
  unknown: {
    label: 'Unidentified',
    reason: 'The classifier could not tell what this is a photograph of.',
  },
}

export function describeKind(kind: ImageKind | null): KindDescription | null {
  return kind === null ? null : DESCRIPTIONS[kind]
}

export function isExcluded(image: ListingImage): boolean {
  // kept_without_processing is a deliberate, permanent opt-out of the
  // pipeline for this one image — the classifier's verdict is left on the
  // record rather than overwritten, so that verdict alone can no longer be
  // the last word on whether this shows as excluded.
  return (
    image.image_kind !== null &&
    image.image_kind !== 'exterior' &&
    !image.kept_without_processing
  )
}

export function pickPreviewImage(images: ListingImage[]): ListingImage | null {
  const processed = images.filter(i => i.image_type === 'processed')
  if (processed.length) return processed[0]

  const originals = images.filter(i => i.image_type === 'original')
  return (
    originals.find(i => i.image_kind === 'exterior') ??
    originals.find(i => i.image_kind === null) ??
    originals[0] ??
    null
  )
}
