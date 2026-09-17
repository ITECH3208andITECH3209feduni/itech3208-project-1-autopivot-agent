// Dashboard — the dealership's recent work, shown as work rather than as
// numbers.
//
// The Figma Make export hardcoded 128 / 1,536 / 3 above a six-row table, and
// the first rebuild kept that shape: three large stat cards, then a list of
// titles against a grey placeholder tile. It answered "how much have we run
// through it" when the question a dealer actually opens the app with is "does
// what came out look good enough to publish". So the vehicles lead, shown
// through their own processed imagery, and any one of them can be opened into
// a full-size before-and-after. The counts stay, but as a masthead line under
// the heading rather than as the subject of the page.
//
// The figures are whatever the dealership's own data says, so a fresh account
// legitimately shows zeroes rather than someone else's numbers.

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type DashboardStats, type ListingImage, type VehicleListing } from '../api/client'
import AuthedImage from '../components/AuthedImage'
import LibraryVehiclePreview from '../components/LibraryVehiclePreview'
import { Card, SolidBtn, StatusPill, TextBtn } from '../components/primitives'
import { C, CARD_SHADOW, MONO, RADIUS_CARD, SANS, serif } from '../design'
import { useMediaQuery } from '../useMediaQuery'

// Each card needs a photograph, and the list endpoint does not return one — see
// the comment on the fetch below — so every vehicle shown costs a request and a
// full-size image download. Eight is enough to fill two rows on a large monitor
// and few enough that the page is not a bandwidth event; the rest are one click
// away under Vehicles.
const GALLERY_LIMIT = 8

// design.ts has one card shadow and no hover elevation, so this is that same
// two-layer ink shadow a step deeper. Kept as a constant rather than inlined so
// the two galleries in this rebuild lift by the same amount.
const RAISED_SHADOW = '0 2px 6px rgba(26,26,23,0.08), 0 10px 24px rgba(26,26,23,0.07)'

/** What a card shows: the processed image if there is one, else the original. */
type Hero = { image: ListingImage; processed: boolean }

/** "2 hours ago" / "Yesterday" / "3 days ago". */
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60000))
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  if (days === 1) return 'Yesterday'
  if (days < 30) return `${days} days ago`
  const months = Math.round(days / 30)
  return `${months} month${months === 1 ? '' : 's'} ago`
}

/**
 * The three counts, as a masthead line.
 *
 * auto-fit rather than auto-fill here, and this is the one place the difference
 * matters: there are exactly three items and they should spread across whatever
 * width they are given. auto-fill would keep laying down empty tracks on a wide
 * monitor and bunch the three of them into the left third.
 */
function StatStrip({ stats }: { stats: DashboardStats | null }) {
  const items = [
    { label: 'Vehicles this month', value: stats?.vehicles_this_month, alert: false },
    { label: 'Images processed', value: stats?.images_processed, alert: false },
    { label: 'Needs review', value: stats?.needs_review, alert: (stats?.needs_review ?? 0) > 0 },
  ]

  return (
    <dl style={{
      display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
      gap: 24, margin: '0 0 40px', padding: 0,
    }}>
      {items.map(item => (
        <div key={item.label} style={{ borderTop: `1px solid ${C.line}`, paddingTop: 12 }}>
          <dt style={{
            fontFamily: MONO, fontSize: 10, letterSpacing: '0.1em', color: C.inkSoft,
            textTransform: 'uppercase', marginBottom: 6,
          }}>
            {item.label}
          </dt>
          <dd style={{
            fontFamily: SANS, fontSize: 22, fontWeight: 500, lineHeight: 1, margin: 0,
            // Rust for a non-zero review queue, matching the "needs review"
            // pill. Nothing else on this line carries colour.
            color: item.alert ? C.rust : C.ink,
          }}>
            {item.value === undefined ? '—' : item.value.toLocaleString()}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function VehicleCard({
  listing, hero, onPreview, stillMoving,
}: {
  listing: VehicleListing
  hero: Hero | null | undefined
  onPreview: () => void
  stillMoving: boolean
}) {
  const [raised, setRaised] = useState(false)
  // The hero is the processed image whenever one exists, so a hero that is an
  // original means nothing on this vehicle has been through the pipeline and
  // there is no comparison to promise.
  const comparable = hero?.processed === true

  return (
    <li
      onClick={onPreview}
      onMouseEnter={() => setRaised(true)}
      onMouseLeave={() => setRaised(false)}
      // Focus bubbles, so tabbing to the title inside lights the card up the
      // same way hovering it does.
      onFocus={() => setRaised(true)}
      onBlur={() => setRaised(false)}
      style={{
        background: C.white, borderRadius: RADIUS_CARD, overflow: 'hidden',
        border: `1px solid ${raised ? C.lineStrong : C.line}`,
        boxShadow: raised ? RAISED_SHADOW : CARD_SHADOW,
        cursor: 'pointer', display: 'flex', flexDirection: 'column',
        transition: stillMoving ? 'box-shadow 0.18s, border-color 0.18s' : undefined,
      }}
    >
      <div style={{ position: 'relative', width: '100%', aspectRatio: '4 / 3', background: C.bone, overflow: 'hidden' }}>
        {hero && (
          <AuthedImage
            src={hero.image.image_url}
            alt={
              hero.processed
                ? `${listing.title}, processed`
                : `${listing.title}, original photograph`
            }
            style={{
              width: '100%', height: '100%', display: 'block',
              transform: raised && stillMoving ? 'scale(1.03)' : 'scale(1)',
              transition: stillMoving ? 'transform 0.4s ease' : undefined,
            }}
          />
        )}

        {/* Solid ink, not a translucent veil: it sits over photography of
            unknown brightness and only a solid ground guarantees the label
            keeps its contrast. Decorative — the button below says the same
            thing to a screen reader. */}
        <span
          aria-hidden
          style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', background: 'rgba(26,26,23,0.7)',
            opacity: raised ? 1 : 0, transition: stillMoving ? 'opacity 0.18s' : undefined,
            pointerEvents: 'none',
          }}
        >
          <span style={{
            fontFamily: MONO, fontSize: 10, letterSpacing: '0.1em',
            textTransform: 'uppercase', color: C.bone,
          }}>
            {comparable ? 'Compare before & after' : 'Preview photographs'}
          </span>
        </span>

        {/* null means the detail request came back with no images at all;
            undefined only means it has not arrived yet, which the empty bone
            well already communicates. */}
        {hero === null && (
          <span style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', fontFamily: MONO, fontSize: 10,
            letterSpacing: '0.1em', textTransform: 'uppercase', color: C.inkSoft,
          }}>
            No photograph
          </span>
        )}
      </div>

      <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          {/* The card is a click target for a mouse, but the button is what a
              keyboard reaches and what carries the action's name. One tab stop
              per card, on the thing that describes it. */}
          <button
            onClick={event => { event.stopPropagation(); onPreview() }}
            aria-label={
              // Contains the visible label — the title — as WCAG 2.5.3 requires
              // of any accessible name that extends what is on screen.
              comparable
                ? `Preview ${listing.title} — before and after`
                : `Preview ${listing.title}`
            }
            style={{
              fontFamily: SANS, fontSize: 15, fontWeight: 500, color: raised ? C.forest : C.ink,
              background: 'none', border: 'none', padding: 0, cursor: 'pointer',
              textAlign: 'left', minWidth: 0, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block',
              transition: stillMoving ? 'color 0.15s' : undefined,
            }}
          >
            {listing.title}
          </button>
          <StatusPill status={listing.processing_status} />
        </div>

        <p style={{ fontFamily: MONO, fontSize: 11, color: C.inkSoft, margin: 0 }}>
          {listing.image_count} image{listing.image_count === 1 ? '' : 's'}
          {hero ? (hero.processed ? ' · processed' : ' · original') : ''}
          {' · '}
          {relativeTime(listing.created_at)}
        </p>
      </div>
    </li>
  )
}

/** Cards with nothing in them, so the gallery does not reflow as it arrives. */
function SkeletonCard() {
  return (
    <li style={{
      background: C.white, borderRadius: RADIUS_CARD, border: `1px solid ${C.line}`,
      boxShadow: CARD_SHADOW, overflow: 'hidden',
    }}>
      <div style={{ width: '100%', aspectRatio: '4 / 3', background: C.bone }} />
      <div style={{ padding: '14px 16px' }}>
        <div style={{ height: 12, width: '65%', background: C.line, borderRadius: 3, marginBottom: 10 }} />
        <div style={{ height: 9, width: '40%', background: C.bone, borderRadius: 3 }} />
      </div>
    </li>
  )
}

export default function DashboardPage() {
  const navigate = useNavigate()
  // Inline styles cannot express a media query, so the motion preference is
  // read the same way the breakpoints are.
  const stillMoving = !useMediaQuery('(prefers-reduced-motion: reduce)')
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [listings, setListings] = useState<VehicleListing[] | null>(null)
  const [heroes, setHeroes] = useState<Record<number, Hero | null>>({})
  const [error, setError] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState<VehicleListing | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const [nextStats, nextListings] = await Promise.all([
          api.dashboardStats(),
          api.listings({ limit: GALLERY_LIMIT }),
        ])
        if (cancelled) return
        setStats(nextStats)
        setListings(nextListings)

        // GET /api/listings returns no imagery at all — not a thumbnail, not a
        // first-image url — so the only way to show a vehicle as a photograph
        // is to ask for each listing in turn. Bounded by GALLERY_LIMIT and run
        // in parallel; a listing whose detail fails simply shows no picture
        // rather than taking the page down with it.
        const details = await Promise.all(
          nextListings.map(listing => api.listing(listing.id).catch(() => null)),
        )
        if (cancelled) return

        const next: Record<number, Hero | null> = {}
        for (const detail of details) {
          if (!detail) continue
          const processed = detail.images.find(i => i.image_type === 'processed')
          const original = detail.images.find(i => i.image_type === 'original')
          const image = processed ?? original
          next[detail.id] = image ? { image, processed: Boolean(processed) } : null
        }
        setHeroes(next)
      } catch (err) {
        if (!cancelled) setError((err as Error).message)
      }
    }

    void load()
    // Guards against setting state after the user has navigated away.
    return () => { cancelled = true }
  }, [])

  return (
    <div>
      <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 24px', letterSpacing: '-0.02em', lineHeight: 1 }}>
        Overview
      </h1>

      {error && (
        <div
          role="alert"
          style={{
            fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
            borderRadius: 8, padding: '12px 16px', marginBottom: 24,
          }}
        >
          {error}
        </div>
      )}

      <StatStrip stats={stats} />

      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        gap: 16, marginBottom: 16,
      }}>
        <h2 style={{ fontFamily: SANS, fontSize: 20, fontWeight: 500, color: C.ink, margin: 0 }}>
          Recent vehicles
        </h2>
        {listings !== null && listings.length > 0 && (
          <TextBtn onClick={() => navigate('/app/vehicles')}>All vehicles</TextBtn>
        )}
      </div>

      {listings !== null && listings.length === 0 ? (
        <Card style={{ padding: '64px 24px', textAlign: 'center' }}>
          <p style={{ fontFamily: SANS, fontSize: 16, color: C.ink, margin: '0 0 8px' }}>
            Nothing has been through the pipeline yet
          </p>
          <p style={{
            fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 auto 24px',
            maxWidth: 440, lineHeight: 1.6,
          }}>
            Add a vehicle and upload its photographs. Once they have been
            processed they appear here, and you can put the original and the
            finished image side by side before anything is published.
          </p>
          <SolidBtn onClick={() => navigate('/app/upload')}>Add a vehicle</SolidBtn>
        </Card>
      ) : (
        // auto-fill, not a column count: on a 32-inch monitor the content column
        // is 1520px and this lays down five tracks, on a laptop three, and
        // neither number appears anywhere in the code.
        <ul style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: 20, listStyle: 'none', margin: 0, padding: 0,
        }}>
          {listings === null
            ? Array.from({ length: 4 }, (_, i) => <SkeletonCard key={i} />)
            : listings.map(listing => (
                <VehicleCard
                  key={listing.id}
                  listing={listing}
                  hero={heroes[listing.id]}
                  stillMoving={stillMoving}
                  onPreview={() => setPreviewing(listing)}
                />
              ))}
        </ul>
      )}

      {previewing && (
        <LibraryVehiclePreview
          listingId={previewing.id}
          title={previewing.title}
          onClose={() => setPreviewing(null)}
        />
      )}
    </div>
  )
}
