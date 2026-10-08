
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type DashboardStats, type ListingImage, type VehicleListing } from '../api/client'
import AuthedImage from '../components/AuthedImage'
import LibraryVehiclePreview from '../components/LibraryVehiclePreview'
import { Card, SolidBtn, StatusPill, TextBtn } from '../components/primitives'
import { C, CARD_SHADOW, MONO, RADIUS_CARD, SANS, serif } from '../design'
import { useMediaQuery } from '../useMediaQuery'

const GALLERY_LIMIT = 8

const RAISED_SHADOW = '0 2px 6px rgba(26,26,23,0.08), 0 10px 24px rgba(26,26,23,0.07)'

type Hero = { image: ListingImage; processed: boolean }

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
  const comparable = hero?.processed === true

  return (
    <li
      onClick={onPreview}
      onMouseEnter={() => setRaised(true)}
      onMouseLeave={() => setRaised(false)}
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
          <button
            onClick={event => { event.stopPropagation(); onPreview() }}
            aria-label={
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
