// A listing and its photographs.
//
// The design shows a before/after comparison with detected angle, matched
// backdrop and plate treatment. None of that exists yet — no image has been
// processed — so this shows what is genuinely there: the originals, and a
// plain statement of what is still missing.

import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api, type Backdrop, type VehicleListingDetail } from '../api/client'
import AuthedImage from '../components/AuthedImage'
import { Card, SolidBtn, StatusPill } from '../components/primitives'
import { C, MONO, RADIUS_CONTROL, SANS, serif } from '../design'

function formatBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024)
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`
}

function ListingPicker() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get('q') ?? ''
  const [listings, setListings] = useState<VehicleListingDetail[] | null>(null)

  useEffect(() => {
    let cancelled = false
    setListings(null)
    api.listings({ limit: 50, q: query || undefined })
      .then(rows => { if (!cancelled) setListings(rows as VehicleListingDetail[]) })
      .catch(() => { if (!cancelled) setListings([]) })
    return () => { cancelled = true }
  }, [query])

  return (
    <div>
      <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 8px', letterSpacing: '-0.02em', lineHeight: 1 }}>
        Vehicles
      </h1>

      {query ? (
        <p style={{
          fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
          textTransform: 'uppercase', margin: '0 0 24px',
        }}>
          {listings === null ? 'Searching' : `${listings.length} matching`} “{query}”
          {' · '}
          <button
            onClick={() => setSearchParams({})}
            style={{
              fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.forest,
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
              textTransform: 'uppercase',
            }}
          >
            Clear
          </button>
        </p>
      ) : (
        <div style={{ height: 24 }} />
      )}

      {listings === null ? (
        <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>Loading…</p>
      ) : listings.length === 0 ? (
        <Card style={{ padding: '64px 24px', textAlign: 'center' }}>
          <p style={{ fontFamily: SANS, fontSize: 16, color: C.ink, margin: '0 0 8px' }}>
            {query ? 'No vehicles match that search' : 'No vehicles yet'}
          </p>
          <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 24px' }}>
            {query
              ? 'Try a make, model, variant or stock number.'
              : 'Add a vehicle and upload its photographs to see it here.'}
          </p>
          {!query && <SolidBtn onClick={() => navigate('/app/upload')}>Add a vehicle</SolidBtn>}
        </Card>
      ) : (
        <Card style={{ overflow: 'hidden' }}>
          {listings.map((listing, i) => (
            <div
              key={listing.id}
              onClick={() => navigate(`/app/vehicles/${listing.id}`)}
              style={{
                display: 'flex', alignItems: 'center', gap: 16, padding: '14px 20px',
                borderTop: i > 0 ? `1px solid ${C.line}` : 'none', cursor: 'pointer',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = C.paper)}
              onMouseLeave={e => (e.currentTarget.style.background = C.white)}
            >
              <div style={{ flex: 1 }}>
                <p style={{ fontFamily: SANS, fontSize: 15, fontWeight: 500, color: C.ink, margin: '0 0 2px' }}>
                  {listing.title}
                </p>
                <p style={{ fontFamily: MONO, fontSize: 11, color: C.inkSoft, margin: 0 }}>
                  {listing.image_count} image{listing.image_count === 1 ? '' : 's'}
                  {listing.stock_number ? ` · stock #${listing.stock_number}` : ''}
                </p>
              </div>
              <StatusPill status={listing.processing_status} />
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}

export default function ResultsView() {
  const { listingId } = useParams()
  const navigate = useNavigate()
  const [listing, setListing] = useState<VehicleListingDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [backdrops, setBackdrops] = useState<Backdrop[]>([])
  const [backdropId, setBackdropId] = useState<number | null>(null)
  const [processing, setProcessing] = useState(false)
  const [processError, setProcessError] = useState<string | null>(null)

  useEffect(() => {
    if (!listingId) return
    let cancelled = false
    api.listing(Number(listingId))
      .then(l => { if (!cancelled) setListing(l) })
      .catch((err: Error) => { if (!cancelled) setError(err.message) })
    api.backdrops()
      .then(b => { if (!cancelled) setBackdrops(b) })
      .catch(() => { /* the library is optional; processing works without one */ })
    return () => { cancelled = true }
  }, [listingId])

  async function startProcessing() {
    if (!listingId) return
    setProcessing(true)
    setProcessError(null)
    try {
      await api.processListing(Number(listingId), backdropId)
      navigate(`/app/processing/${listingId}`)
    } catch (err) {
      setProcessError((err as Error).message)
    } finally {
      setProcessing(false)
    }
  }

  if (!listingId) return <ListingPicker />

  if (error) {
    return (
      <div>
        <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 24px', letterSpacing: '-0.02em' }}>Results</h1>
        <div role="alert" style={{
          fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
          borderRadius: 8, padding: '12px 16px',
        }}>
          {error}
        </div>
      </div>
    )
  }

  if (!listing) {
    return <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>Loading…</p>
  }

  const originals = listing.images.filter(i => i.image_type === 'original')
  const processed = listing.images.filter(i => i.image_type === 'processed')

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 24, marginBottom: 8 }}>
        <h1 style={{ ...serif(40), color: C.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.05 }}>
          {listing.title}
        </h1>
        <StatusPill status={listing.processing_status} />
      </div>
      <p style={{
        fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
        textTransform: 'uppercase', margin: '0 0 32px',
      }}>
        {listing.stock_number ? `Stock #${listing.stock_number} · ` : ''}
        {originals.length} image{originals.length === 1 ? '' : 's'}
      </p>

      {originals.length === 0 ? (
        <Card style={{ padding: '48px 24px', textAlign: 'center' }}>
          <p style={{ fontFamily: SANS, fontSize: 15, color: C.inkSoft, margin: 0 }}>
            This listing has no photographs yet.
          </p>
        </Card>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 16 }}>
          {originals.map(image => (
            <Card key={image.id} style={{ overflow: 'hidden' }}>
              <AuthedImage
                src={image.image_url}
                alt={image.original_filename}
                style={{ width: '100%', height: 150, display: 'block' }}
              />
              <div style={{ padding: '10px 12px' }}>
                <p style={{
                  fontFamily: SANS, fontSize: 13, color: C.ink, margin: '0 0 2px',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {image.original_filename}
                </p>
                <p style={{ fontFamily: MONO, fontSize: 10, color: C.inkSoft, margin: 0 }}>
                  {image.width} × {image.height} · {formatBytes(image.file_size_bytes)}
                </p>
              </div>
            </Card>
          ))}
        </div>
      )}

      {processed.length > 0 && (
        <>
          <p style={{ fontFamily: SANS, fontSize: 20, fontWeight: 500, color: C.ink, margin: '32px 0 16px' }}>
            Processed
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 16 }}>
            {processed.map(image => (
              <Card key={image.id} style={{ overflow: 'hidden' }}>
                <AuthedImage
                  src={image.image_url}
                  alt={`Processed ${image.original_filename}`}
                  style={{ width: '100%', height: 150, display: 'block' }}
                />
                <div style={{ padding: '10px 12px' }}>
                  <p style={{ fontFamily: MONO, fontSize: 10, color: C.inkSoft, margin: 0 }}>
                    {image.width} × {image.height} · {formatBytes(image.file_size_bytes)}
                  </p>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      {originals.length > 0 && (
        <Card style={{ padding: 20, marginTop: 24, maxWidth: 640 }}>
          <p style={{ fontFamily: SANS, fontSize: 16, fontWeight: 500, color: C.ink, margin: '0 0 4px' }}>
            {processed.length ? 'Process remaining photographs' : 'Process these photographs'}
          </p>
          <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 16px', lineHeight: 1.6 }}>
            Vehicle detection, background removal, plate masking, then the chosen
            backdrop. Without one the vehicle comes back on transparency.
          </p>

          {processError && (
            <div role="alert" style={{
              fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
              borderRadius: 8, padding: '10px 14px', marginBottom: 16,
            }}>
              {processError}
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <select
              value={backdropId ?? ''}
              onChange={e => setBackdropId(e.target.value ? Number(e.target.value) : null)}
              style={{
                fontFamily: SANS, fontSize: 14, color: C.ink, background: C.paper,
                border: `1px solid ${C.lineStrong}`, borderRadius: RADIUS_CONTROL,
                padding: '10px 14px', minWidth: 200,
              }}
            >
              <option value="">No backdrop (transparent)</option>
              {backdrops.map(b => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
            <SolidBtn onClick={startProcessing} disabled={processing}>
              {processing ? 'Starting…' : 'Start processing'}
            </SolidBtn>
          </div>

          {backdrops.length === 0 && (
            <p style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft, margin: '12px 0 0' }}>
              Your backdrop library is empty — add one under Backdrops to composite
              onto a scene.
            </p>
          )}
        </Card>
      )}

      <div style={{ marginTop: 24 }}>
        <SolidBtn onClick={() => navigate('/app/vehicles')}>All vehicles</SolidBtn>
      </div>
    </div>
  )
}
