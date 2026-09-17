// What the classifier decided a photograph is, said in a dealer's words.
//
// `image_kind` is set on import and is not the same thing as `image_type`: a
// URL import drags in advertisement banners, dealer badges, interior shots and
// part close-ups alongside the vehicle, and only an exterior shot can be cut
// out and composited onto a backdrop. This vocabulary lives in its own module
// because two screens have to agree on it — the vehicles list picks the
// photograph that best represents a vehicle, and the detail view has to explain
// why the others were left out. Two copies of that judgement would drift.

import type { ImageKind, ListingImage } from '../api/client'

export type KindDescription = {
  /** The badge on the tile. */
  label: string
  /** Why the pipeline left this photograph out, in a full sentence. */
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

/** Null when nothing has classified the photograph yet. */
export function describeKind(kind: ImageKind | null): KindDescription | null {
  return kind === null ? null : DESCRIPTIONS[kind]
}

/**
 * Whether a photograph was left out of the composited listing.
 *
 * A null kind is deliberately NOT excluded. Null means the classifier has not
 * looked yet — everything uploaded before the classifier existed is null — and
 * greying out a dealer's entire library because a column is unpopulated would
 * be a far worse failure than showing one advertisement too many.
 */
export function isExcluded(image: ListingImage): boolean {
  return image.image_kind !== null && image.image_kind !== 'exterior'
}

/**
 * The one photograph that should stand for a vehicle in the list.
 *
 * A processed shot first, because that is the image the dealer is actually
 * selling with. Failing that the best original: a known exterior, then an
 * unclassified one, and only then whatever is left — a card showing an
 * advertisement banner is still better than an empty grey well, provided the
 * detail view is honest about what it is.
 */
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
