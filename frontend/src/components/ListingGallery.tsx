// The listing preview: one large photograph with a thumbnail strip beneath it.
//
// This is how a buyer meets a car on a dealer's website, and it is what the
// dealer is checking when they open a vehicle here — not a file listing. The
// previous screen showed a flat grid of every file with its pixel dimensions
// and byte size underneath, which answered questions nobody was asking and
// buried the only one that matters: does this look like a car worth driving to
// see?
//
// The photograph sits on ink, per guidelines §4: dark grounds are reserved for
// imagery so the surrounding interface recedes and the vehicle dominates. It is
// contained rather than cropped — a hero that crops a wagon's nose off is worse
// than a letterboxed one, because the dealer cannot tell whether the pipeline
// or the frame did it.
//
// Built as a tab list over a single panel. That is genuinely what a gallery is,
// and it buys the arrow-key behaviour, the "selected" announcement and the
// single tab stop that twenty separate buttons would not.

import { useId, useRef, type CSSProperties, type KeyboardEvent } from 'react'

import type { ListingImage } from '../api/client'
import { C, MONO, RADIUS_CARD, SANS } from '../design'
import AuthedImage from './AuthedImage'

const THUMB_RADIUS = 8

const arrowStyle = (side: 'left' | 'right'): CSSProperties => ({
  position: 'absolute',
  [side]: 12,
  top: '50%',
  transform: 'translateY(-50%)',
  width: 36,
  height: 36,
  borderRadius: '50%',
  border: 'none',
  // Bone rather than a translucent ink: a dark chip on a dark photograph
  // disappears, and the arrow has to stay visible over whatever is behind it.
  background: 'rgba(245,242,236,0.92)',
  color: C.ink,
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: 0,
})

function Chevron({ direction }: { direction: 'left' | 'right' }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d={direction === 'left' ? 'M10 3L5 8l5 5' : 'M6 3l5 5-5 5'}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export default function ListingGallery({
  images,
  index,
  onIndexChange,
  altPrefix,
  label,
  thumbMin = 96,
  onDelete,
}: {
  images: ListingImage[]
  index: number
  onIndexChange: (index: number) => void
  /** Prefixes every alt text; the position within the set is appended. */
  altPrefix: string
  /** Names the strip for a screen reader, e.g. "Processed photographs". */
  label: string
  thumbMin?: number
  /** Omitted where removal does not apply; shown as a labelled control when given. */
  onDelete?: (image: ListingImage) => void
}) {
  const baseId = useId()
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])

  // Deleting the last photograph leaves the caller's index past the end for one
  // render, so the clamp lives here rather than trusting every caller to reset.
  const safe = Math.min(Math.max(index, 0), images.length - 1)
  const current = images[safe]

  // The caller renders its own empty state; there is nothing sensible to draw
  // from an empty set.
  if (!current) return null

  function select(next: number, moveFocus = false) {
    const wrapped = (next + images.length) % images.length
    onIndexChange(wrapped)
    // The thumbnail buttons all exist regardless of which is selected, so focus
    // can move immediately without waiting for the re-render.
    if (moveFocus) tabRefs.current[wrapped]?.focus()
  }

  function onStripKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const moves: Record<string, number | undefined> = {
      ArrowRight: safe + 1,
      ArrowLeft: safe - 1,
      Home: 0,
      End: images.length - 1,
    }
    const next = moves[event.key]
    if (next === undefined) return
    event.preventDefault()
    select(next, true)
  }

  const panelId = `${baseId}-panel`

  return (
    <div>
      <div
        id={panelId}
        role="tabpanel"
        aria-labelledby={`${baseId}-tab-${safe}`}
        // Only made focusable when it holds nothing focusable itself: with more
        // than one photograph the previous/next buttons are inside it.
        tabIndex={images.length > 1 ? undefined : 0}
        style={{
          position: 'relative',
          background: C.ink,
          borderRadius: RADIUS_CARD,
          overflow: 'hidden',
          aspectRatio: '16 / 9',
          maxHeight: '60vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <AuthedImage
          key={current.id}
          src={current.image_url}
          alt={`${altPrefix} — ${safe + 1} of ${images.length}`}
          style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
        />

        {images.length > 1 && (
          <>
            <button
              onClick={() => select(safe - 1)}
              aria-label="Previous photograph"
              style={arrowStyle('left')}
            >
              <Chevron direction="left" />
            </button>
            <button
              onClick={() => select(safe + 1)}
              aria-label="Next photograph"
              style={arrowStyle('right')}
            >
              <Chevron direction="right" />
            </button>
          </>
        )}
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 16, flexWrap: 'wrap', padding: '10px 2px 0',
      }}>
        <p style={{
          fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
          textTransform: 'uppercase', margin: 0,
        }}>
          {/* Position and resolution only. The byte size of a JPEG tells a
              dealer nothing about whether the photograph is any good. */}
          {String(safe + 1).padStart(2, '0')} / {String(images.length).padStart(2, '0')}
          {' · '}{current.width} × {current.height}
        </p>

        {onDelete && (
          <button
            onClick={() => onDelete(current)}
            aria-label={`Remove photograph ${safe + 1} of ${images.length}`}
            style={{
              fontFamily: SANS, fontSize: 13, color: C.inkSoft, background: 'none',
              border: 'none', cursor: 'pointer', padding: 0,
            }}
            onMouseEnter={e => (e.currentTarget.style.color = C.rust)}
            onMouseLeave={e => (e.currentTarget.style.color = C.inkSoft)}
          >
            Remove this photograph
          </button>
        )}
      </div>

      <div
        role="tablist"
        aria-label={label}
        aria-orientation="horizontal"
        style={{
          display: 'grid',
          // auto-fill so the strip is four thumbnails on a laptop and a dozen
          // on a 32-inch monitor without either being told a column count.
          gridTemplateColumns: `repeat(auto-fill, minmax(${thumbMin}px, 1fr))`,
          gap: 8,
          marginTop: 12,
        }}
      >
        {images.map((image, i) => (
          <button
            key={image.id}
            ref={element => { tabRefs.current[i] = element }}
            role="tab"
            id={`${baseId}-tab-${i}`}
            aria-selected={i === safe}
            aria-controls={panelId}
            tabIndex={i === safe ? 0 : -1}
            onClick={() => select(i)}
            onKeyDown={onStripKeyDown}
            style={{
              position: 'relative', padding: 0, border: 'none', background: C.bone,
              borderRadius: THUMB_RADIUS, overflow: 'hidden', cursor: 'pointer',
              aspectRatio: '4 / 3', display: 'block',
            }}
          >
            <AuthedImage
              src={image.image_url}
              alt={`${altPrefix} — ${i + 1} of ${images.length}`}
              style={{ width: '100%', height: '100%', display: 'block' }}
            />
            {/* The selected ring is an overlay rather than a border on the
                button, so selecting a thumbnail cannot nudge the grid by the
                one pixel a border width change would add. */}
            <span
              aria-hidden
              style={{
                position: 'absolute', inset: 0, borderRadius: THUMB_RADIUS,
                border: i === safe ? `2px solid ${C.forest}` : `1px solid ${C.line}`,
              }}
            />
          </button>
        ))}
      </div>
    </div>
  )
}
