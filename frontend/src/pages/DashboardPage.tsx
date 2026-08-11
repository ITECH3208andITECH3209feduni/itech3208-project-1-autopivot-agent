// Dashboard, reading from GET /api/dashboard/stats and GET /api/listings.
//
// The Figma Make export hardcoded 128 / 1,536 / 3 and a six-row array. These
// figures are whatever the dealership's own data says, so a fresh account
// legitimately shows zeroes rather than someone else's numbers.

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type DashboardStats, type VehicleListing } from '../api/client'
import { C, CARD_SHADOW, MONO, RADIUS_CARD, SANS, serif } from '../design'
import { SolidBtn, StatusPill } from '../components/primitives'
import { useIsMobile } from '../useMediaQuery'

/** "2 hours ago" / "Yesterday" / "3 days ago", matching the design's column. */
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

function StatCard({ label, value }: { label: string; value: number | null }) {
  return (
    <div style={{
      background: C.white, borderRadius: RADIUS_CARD, border: `1px solid ${C.line}`,
      boxShadow: CARD_SHADOW, padding: 24,
    }}>
      <div style={{
        fontFamily: MONO, fontSize: 11, letterSpacing: '0.1em', color: C.inkSoft,
        marginBottom: 10, textTransform: 'uppercase',
      }}>
        {label}
      </div>
      <div style={{ fontFamily: SANS, fontSize: 32, fontWeight: 500, color: C.ink, lineHeight: 1 }}>
        {value === null ? '—' : value.toLocaleString()}
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const mobile = useIsMobile()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [listings, setListings] = useState<VehicleListing[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([api.dashboardStats(), api.listings({ limit: 20 })])
      .then(([s, l]) => {
        if (cancelled) return
        setStats(s)
        setListings(l)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    // Guards against setting state after the user has navigated away.
    return () => { cancelled = true }
  }, [])

  return (
    <div>
      <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 32px', letterSpacing: '-0.02em', lineHeight: 1 }}>
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

      <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1fr' : 'repeat(3, 1fr)', gap: 16, marginBottom: 32 }}>
        <StatCard label="Vehicles this month" value={stats?.vehicles_this_month ?? null} />
        <StatCard label="Images processed" value={stats?.images_processed ?? null} />
        <StatCard label="Needs review" value={stats?.needs_review ?? null} />
      </div>

      <p style={{ fontFamily: SANS, fontSize: 20, fontWeight: 500, color: C.ink, margin: '0 0 16px' }}>
        Recent vehicles
      </p>
      <div style={{
        background: C.white, borderRadius: RADIUS_CARD, border: `1px solid ${C.line}`,
        boxShadow: CARD_SHADOW, overflow: 'hidden',
      }}>
        {listings === null ? (
          <div style={{ padding: '48px 24px', textAlign: 'center', fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>
            Loading…
          </div>
        ) : listings.length === 0 ? (
          <div style={{ padding: '64px 24px', textAlign: 'center' }}>
            <p style={{ fontFamily: SANS, fontSize: 16, color: C.ink, margin: '0 0 8px' }}>
              No vehicles processed yet
            </p>
            <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 24px' }}>
              Add a vehicle and upload its photographs to get started
            </p>
            <SolidBtn onClick={() => navigate('/app/upload')}>Add a vehicle</SolidBtn>
          </div>
        ) : (
          listings.map((v, i) => (
            <div
              key={v.id}
              onClick={() => navigate(`/app/vehicles/${v.id}`)}
              style={{
                display: 'flex', alignItems: 'center', gap: 16, padding: '14px 20px',
                borderTop: i > 0 ? `1px solid ${C.line}` : 'none',
                cursor: 'pointer', transition: 'background 0.12s',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = C.paper)}
              onMouseLeave={e => (e.currentTarget.style.background = C.white)}
            >
              {/* Placeholder tile. Real thumbnails need file storage, which
                  does not exist yet — storage_path points at files nothing
                  has written. */}
              <div style={{
                width: 64, height: 44, borderRadius: 8, flexShrink: 0,
                background: C.line,
              }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{
                  fontFamily: SANS, fontSize: 15, fontWeight: 500, color: C.ink,
                  margin: '0 0 2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {v.title}
                </p>
                <p style={{ fontFamily: MONO, fontSize: 11, color: C.inkSoft, margin: 0 }}>
                  {v.image_count} image{v.image_count === 1 ? '' : 's'} · {relativeTime(v.created_at)}
                </p>
              </div>
              <StatusPill status={v.processing_status} />
            </div>
          ))
        )}
      </div>
    </div>
  )
}
