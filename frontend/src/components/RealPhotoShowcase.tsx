
// A real vehicle's own photographs, shown on the public coming-soon page.
//
// These are plain static files under frontend/public/demo-car — Vite serves
// anything there from the site root with no auth and no build step — so this
// component renders them as ordinary <img src="/demo-car/...">, never
// through AuthedImage/api.fetchFile. That authenticated path needs a bearer
// token and a dealership match; a logged-out visitor on this page has
// neither and would just get a 401, so it must never be reached from here.
//
// No angle has a processed ("after") image yet — that is a deliberate
// product decision, not a gap to paper over, so each angle renders as the
// real "before" photo alone with an honest caption. `Frame` mirrors
// LibraryVehiclePreview's `Comparison` fallback shape exactly: the
// "Original" badge always shows, and the second image layer, the divider,
// the "Processed" badge and the range slider all key off one thing, whether
// `angle.after` is set. So the day a real composited image is added to an
// angle's `after`, this same component renders the real before/after slider
// for it — no rework, just data.

import { useRef, useState, type CSSProperties, type PointerEvent } from 'react'

import { C, MONO, RADIUS_CARD, RADIUS_CONTROL, SANS, serif } from '../design'
import { useIsCompact } from '../useMediaQuery'

export type ShowcaseAngle = {
  id: string
  label: string
  /** The real, unedited photograph. A static /demo-car/*.jpg path. */
  before: string
  /** The composited result for this angle. Absent until one exists. */
  after?: string
}

// Order and labels match the mobile capture app's own walking order for this
// exact 8-shot sequence (mobile/lib/features/capture/capture_angles.dart):
// front, all the way around one side, back to the front on the other side.
export const SHOWCASE_ANGLES: ShowcaseAngle[] = [
  { id: 'front', label: 'Front', before: '/demo-car/front.jpg' },
  { id: 'frontRightCorner', label: 'Front-right corner', before: '/demo-car/frontRightCorner.jpg' },
  { id: 'rightSide', label: 'Right side', before: '/demo-car/rightSide.jpg' },
  { id: 'rearRightCorner', label: 'Rear-right corner', before: '/demo-car/rearRightCorner.jpg' },
  { id: 'rear', label: 'Rear', before: '/demo-car/rear.jpg' },
  { id: 'rearLeftCorner', label: 'Rear-left corner', before: '/demo-car/rearLeftCorner.jpg' },
  { id: 'leftSide', label: 'Left side', before: '/demo-car/leftSide.jpg' },
  { id: 'frontLeftCorner', label: 'Front-left corner', before: '/demo-car/frontLeftCorner.jpg' },
]

// The demo photographs are already sized ~788x1400 for web — a portrait
// phone shot, not a landscape studio one. The frame mirrors that ratio so a
// real photo fills it edge to edge instead of letterboxing inside a box
// shaped for something else.
const FRAME_RATIO = '788 / 1400'

const BADGE: CSSProperties = {
  position: 'absolute', bottom: 12, background: C.ink, color: C.bone,
  fontFamily: MONO, fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase',
  padding: '4px 8px', borderRadius: 4, border: '1px solid rgba(226,222,214,0.2)',
}

function Frame({ angle }: { angle: ShowcaseAngle }) {
  const [split, setSplit] = useState(50)
  const dragging = useRef(false)
  const after = angle.after

  const layer: CSSProperties = {
    position: 'absolute', inset: 0, width: '100%', height: '100%',
    objectFit: 'cover', display: 'block',
  }

  function moveTo(event: PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    const percent = ((event.clientX - rect.left) / rect.width) * 100
    setSplit(Math.min(100, Math.max(0, percent)))
  }

  return (
    <div>
      <div
        style={{
          position: 'relative', width: '100%', aspectRatio: FRAME_RATIO,
          background: C.ink, overflow: 'hidden', borderRadius: RADIUS_CARD,
          border: '1px solid rgba(226,222,214,0.14)',
          touchAction: after ? 'none' : undefined, cursor: after ? 'ew-resize' : 'default',
        }}
        onPointerDown={after ? event => {
          dragging.current = true
          event.currentTarget.setPointerCapture(event.pointerId)
          moveTo(event)
        } : undefined}
        onPointerMove={after ? event => { if (dragging.current) moveTo(event) } : undefined}
        onPointerUp={after ? () => { dragging.current = false } : undefined}
        onPointerCancel={after ? () => { dragging.current = false } : undefined}
      >
        <img
          src={angle.before}
          alt={`${angle.label} photograph of the vehicle, unedited`}
          style={layer}
        />

        {after && (
          <div style={{ position: 'absolute', inset: 0, clipPath: `inset(0 0 0 ${split}%)` }}>
            <img
              src={after}
              alt={`${angle.label} photograph of the vehicle after processing`}
              style={layer}
            />
          </div>
        )}

        {after && (
          <div
            aria-hidden
            style={{
              position: 'absolute', top: 0, bottom: 0, left: `${split}%`,
              width: 2, marginLeft: -1, background: C.bone,
              boxShadow: '0 0 8px rgba(26,26,23,0.5)',
            }}
          >
            <span style={{
              position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
              width: 32, height: 32, borderRadius: '50%', background: C.bone,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <svg width="16" height="10" viewBox="0 0 16 10" fill="none">
                <path
                  d="M5 1L1 5l4 4M11 1l4 4-4 4"
                  stroke={C.ink} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
                />
              </svg>
            </span>
          </div>
        )}

        <span style={{ ...BADGE, left: 12 }}>Original</span>
        {after && <span style={{ ...BADGE, right: 12 }}>Processed</span>}
      </div>

      {after ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '16px 0 0' }}>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={Math.round(split)}
            onChange={event => setSplit(Number(event.target.value))}
            aria-label="Before and after divider"
            aria-valuetext={`${Math.round(split)} percent original, ${100 - Math.round(split)} percent processed`}
            style={{ flex: 1, accentColor: C.bone, cursor: 'ew-resize' }}
          />
          <button
            onClick={() => setSplit(split > 50 ? 0 : 100)}
            style={{
              fontFamily: MONO, fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
              color: C.bone, background: 'none', border: '1px solid rgba(226,222,214,0.3)',
              borderRadius: RADIUS_CONTROL, padding: '6px 12px', cursor: 'pointer', whiteSpace: 'nowrap',
            }}
          >
            {split > 50 ? 'Show processed' : 'Show original'}
          </button>
        </div>
      ) : (
        <p style={{
          fontFamily: SANS, fontSize: 13, color: C.bone, opacity: 0.55,
          margin: '14px 0 0', lineHeight: 1.6, textAlign: 'center',
        }}>
          This is the original, unedited photograph. The processed version is coming soon.
        </p>
      )}
    </div>
  )
}

export default function RealPhotoShowcase({ angles = SHOWCASE_ANGLES }: { angles?: ShowcaseAngle[] }) {
  const compact = useIsCompact()
  const [selected, setSelected] = useState(0)
  const angle = angles[selected] ?? angles[0]

  if (!angle) return null

  return (
    <section style={{
      background: C.ink, borderTop: '1px solid rgba(226,222,214,0.1)',
      padding: compact ? '56px 20px' : '80px 32px',
    }}>
      <div style={{ maxWidth: 920, margin: '0 auto' }}>
        <div style={{
          fontFamily: MONO, fontSize: 11, color: C.bone, opacity: 0.45,
          letterSpacing: '0.14em', textTransform: 'uppercase', marginBottom: 20,
          textAlign: 'center',
        }}>
          See it for yourself
        </div>

        <h2 style={{
          ...serif(40), color: C.bone, margin: '0 0 16px',
          letterSpacing: '-0.02em', lineHeight: 1.1, textAlign: 'center',
        }}>
          A real car, not a mockup.
        </h2>

        <p style={{
          fontFamily: SANS, fontSize: 16, color: C.bone, opacity: 0.65,
          margin: '0 auto 40px', lineHeight: 1.6, maxWidth: 560, textAlign: 'center',
        }}>
          Eight angles of an actual customer vehicle, straight off a dealership
          camera — completely unedited. The processed, publish-ready version is
          coming soon.
        </p>

        <div style={{ maxWidth: 340, margin: '0 auto' }}>
          <Frame angle={angle} />
        </div>

        <div
          role="group"
          aria-label="Choose a photograph angle"
          style={{
            display: 'flex', gap: 8, flexWrap: compact ? 'nowrap' : 'wrap',
            justifyContent: 'center', overflowX: compact ? 'auto' : 'visible',
            marginTop: 24, paddingBottom: 4,
          }}
        >
          {angles.map((candidate, index) => {
            const isSelected = index === selected
            return (
              <button
                key={candidate.id}
                onClick={() => setSelected(index)}
                aria-pressed={isSelected}
                style={{
                  flexShrink: 0, padding: 0, background: 'none', cursor: 'pointer',
                  borderRadius: RADIUS_CONTROL, overflow: 'hidden',
                  border: isSelected ? `1px solid ${C.bone}` : '1px solid rgba(226,222,214,0.18)',
                  opacity: isSelected ? 1 : 0.7, transition: 'opacity 0.15s, border-color 0.15s',
                }}
              >
                <img
                  src={candidate.before}
                  alt=""
                  style={{ width: 46, height: 64, objectFit: 'cover', display: 'block' }}
                />
                <div style={{
                  fontFamily: MONO, fontSize: 9, letterSpacing: '0.03em', textTransform: 'uppercase',
                  color: isSelected ? C.ink : C.bone, background: isSelected ? C.bone : 'rgba(26,26,23,0.85)',
                  padding: '3px 2px', textAlign: 'center', whiteSpace: 'nowrap',
                }}>
                  {candidate.label}
                </div>
              </button>
            )
          })}
        </div>
      </div>
    </section>
  )
}
