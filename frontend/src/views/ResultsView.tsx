// A dealership's vehicles, and one vehicle's listing preview.
//
// Two routes, one file: /app/vehicles is the stock list, /app/vehicles/:id is
// the vehicle. Both were previously drawn as file management — a table of
// titles and counts, then two labelled grids of every file with its pixel
// dimensions and byte size beneath it. That is an inventory export, not a
// listing. A dealer opening a vehicle is asking one question: does this look
// like a car worth driving across town for? So the detail view is a hero
// photograph with a thumbnail strip, and the list shows each vehicle by its
// best processed shot.
//
// Where this departs from the Figma design:
//
//   · The design shows a before/after slider with the detected angle and plate
//     treatment written under each pair. The API returns no link from a
//     processed image back to the original it came from, so nothing here can
//     honestly claim "this is that photograph, fixed". Originals live behind a
//     toggle instead: still one click away for the comparison a dealer needs,
//     without inventing a pairing the data does not support.
//   · The design has no notion of a photograph the pipeline refused. A URL
//     import drags in advertisement banners, dealer badges, interior shots and
//     part close-ups, and only exteriors can be composited — so those are shown
//     below the listing, greyed, each one saying why it is there and offering
//     to remove itself.
//   · No description or marketing copy. This is a preview of the imagery, and
//     the listing text is not a thing the product writes yet.

import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import {
  api,
  type Backdrop,
  type ListingImage,
  type VehicleListing,
  type VehicleListingDetail,
} from '../api/client'
import AuthedImage from '../components/AuthedImage'
import ListingCard from '../components/ListingCard'
import ListingGallery from '../components/ListingGallery'
import { describeKind, isExcluded, pickPreviewImage } from '../components/ListingImageKind'
import { Card, ConfirmDialog, SolidBtn, StatusPill, Stepper } from '../components/primitives'
import { C, MONO, RADIUS_CONTROL, SANS, serif } from '../design'
import { useIsMobile } from '../useMediaQuery'
import { WORKFLOW_STEPS, stepHref, type WorkflowStep } from '../workflow'

/** How many vehicles one screen holds before the dealer is asked to search. */
const PAGE_SIZE = 24

/**
 * Preview requests in flight at once.
 *
 * The list endpoint returns no imagery at all, so the only way to show a
 * dealer their stock today is one detail request per vehicle. Four at a time
 * leaves room in the browser's per-host connection pool for the photographs
 * themselves, which are the point; firing twenty-four at once starves them.
 */
const PREVIEW_CONCURRENCY = 4

function Alert({ children }: { children: ReactNode }) {
  return (
    <div role="alert" style={{
      fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
      borderRadius: 8, padding: '12px 16px', marginBottom: 24, lineHeight: 1.6,
    }}>
      {children}
    </div>
  )
}

const metaLine: CSSProperties = {
  fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
  textTransform: 'uppercase', margin: 0,
}

const sectionHeading: CSSProperties = {
  fontFamily: SANS, fontSize: 18, fontWeight: 500, color: C.ink, margin: '0 0 4px',
}

const quietBody: CSSProperties = {
  fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0, lineHeight: 1.6,
}

/** A destructive control that reads as secondary until you are hovering it. */
function RemoveBtn({ label, ariaLabel, onClick }: {
  label: string
  ariaLabel: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      aria-label={ariaLabel}
      style={{
        fontFamily: SANS, fontSize: 13, color: C.inkSoft, background: 'none',
        border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left',
      }}
      onMouseEnter={e => (e.currentTarget.style.color = C.rust)}
      onMouseLeave={e => (e.currentTarget.style.color = C.inkSoft)}
      onFocus={e => (e.currentTarget.style.color = C.rust)}
      onBlur={e => (e.currentTarget.style.color = C.inkSoft)}
    >
      {label}
    </button>
  )
}

// ── The vehicles list ────────────────────────────────────────────────────────

function VehiclesList() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get('q') ?? ''

  const [listings, setListings] = useState<VehicleListing[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Keyed by listing id. Absent means the preview has not arrived yet, which is
  // what ListingCard draws as "Loading" rather than as "No photographs".
  const [previews, setPreviews] = useState<Record<number, ListingImage | null>>({})

  useEffect(() => {
    let cancelled = false
    setListings(null)
    setPreviews({})
    setError(null)
    api.listings({ limit: PAGE_SIZE, q: query || undefined })
      .then(rows => { if (!cancelled) setListings(rows) })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message)
          setListings([])
        }
      })
    return () => { cancelled = true }
  }, [query])

  useEffect(() => {
    if (!listings || listings.length === 0) return
    let cancelled = false
    const queue = [...listings]

    async function worker() {
      for (;;) {
        const next = queue.shift()
        if (!next || cancelled) return
        try {
          const detail = await api.listing(next.id)
          if (cancelled) return
          setPreviews(current => ({ ...current, [next.id]: pickPreviewImage(detail.images) }))
        } catch {
          // A vehicle whose detail will not load still belongs on the screen;
          // it simply shows without a photograph.
          if (!cancelled) setPreviews(current => ({ ...current, [next.id]: null }))
        }
      }
    }

    const workers = Array.from(
      { length: Math.min(PREVIEW_CONCURRENCY, queue.length) },
      () => worker(),
    )
    void Promise.all(workers)

    return () => { cancelled = true }
  }, [listings])

  return (
    <div>
      <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 8px', letterSpacing: '-0.02em', lineHeight: 1 }}>
        Vehicles
      </h1>

      {query ? (
        <p style={{ ...metaLine, margin: '0 0 24px' }}>
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

      {error && <Alert>{error}</Alert>}

      {listings === null ? (
        <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>Loading…</p>
      ) : listings.length === 0 ? (
        // Suppressed when the request itself failed: "No vehicles yet" is a
        // lie when the truth is that the server could not be reached.
        error ? null : (
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
        )
      ) : (
        <>
          <div style={{
            display: 'grid',
            // auto-fill, so the same grid is two columns on a laptop and six on
            // a 32-inch monitor without a breakpoint being consulted.
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
            gap: 20,
          }}>
            {listings.map(listing => (
              <ListingCard
                key={listing.id}
                listing={listing}
                preview={previews[listing.id]}
                onOpen={() => navigate(`/app/vehicles/${listing.id}`)}
              />
            ))}
          </div>

          {listings.length === PAGE_SIZE && (
            <p style={{ ...metaLine, marginTop: 24 }}>
              Showing the {PAGE_SIZE} most recent — search to narrow this down
            </p>
          )}
        </>
      )}
    </div>
  )
}

// ── One vehicle ──────────────────────────────────────────────────────────────

type GalleryMode = 'processed' | 'original'

/** A photograph the pipeline left out, shown greyed with the reason it was. */
function ExcludedTile({ image, onRemove }: {
  image: ListingImage
  onRemove: () => void
}) {
  const kind = describeKind(image.image_kind)
  const label = kind?.label ?? 'Not classified'

  return (
    <Card style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{ aspectRatio: '4 / 3', background: C.bone }}>
        {/* Greyed and faded so it cannot be mistaken for part of the listing.
            Only the photograph is dimmed — the label and reason below stay at
            full strength, because dimming text is how contrast requirements
            get quietly broken. */}
        <AuthedImage
          src={image.image_url}
          alt={`${label} — ${image.original_filename}`}
          style={{
            width: '100%', height: '100%', display: 'block',
            filter: 'grayscale(0.9)', opacity: 0.62,
          }}
        />
      </div>
      <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
        <span style={{
          fontFamily: SANS, fontSize: 12, fontWeight: 500, color: C.inkSoft,
          background: 'rgba(26,26,23,0.05)', borderRadius: 999, padding: '3px 10px',
          alignSelf: 'flex-start',
        }}>
          {label}
          {image.kind_confidence !== null && ` · ${Math.round(image.kind_confidence * 100)}%`}
        </span>
        <p style={{ ...quietBody, fontSize: 13 }}>
          {kind?.reason ?? 'Nothing has classified this photograph yet.'}
        </p>
        <p style={{
          fontFamily: MONO, fontSize: 10, color: C.inkSoft, margin: 0,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>
          {image.original_filename}
        </p>
        <div style={{ marginTop: 'auto', paddingTop: 4 }}>
          <RemoveBtn
            label="Remove"
            ariaLabel={`Remove ${image.original_filename}`}
            onClick={onRemove}
          />
        </div>
      </div>
    </Card>
  )
}

function ModeToggle({ mode, onChange, processedCount, originalCount }: {
  mode: GalleryMode
  onChange: (mode: GalleryMode) => void
  processedCount: number
  originalCount: number
}) {
  const options: { key: GalleryMode; label: string; count: number }[] = [
    { key: 'processed', label: 'Processed', count: processedCount },
    { key: 'original', label: 'Originals', count: originalCount },
  ]

  return (
    <div
      role="group"
      aria-label="Which photographs to show"
      style={{
        display: 'inline-flex', gap: 4, padding: 4,
        background: C.paper, border: `1px solid ${C.line}`, borderRadius: RADIUS_CONTROL,
      }}
    >
      {options.map(option => {
        const active = option.key === mode
        return (
          <button
            key={option.key}
            onClick={() => onChange(option.key)}
            aria-pressed={active}
            style={{
              fontFamily: SANS, fontSize: 13, fontWeight: active ? 500 : 400,
              color: active ? C.forest : C.inkSoft,
              background: active ? C.forestTint : 'none',
              border: `1px solid ${active ? C.forest : 'transparent'}`,
              borderRadius: 7, padding: '6px 14px', cursor: 'pointer',
            }}
          >
            {option.label}
            <span style={{ fontFamily: MONO, fontSize: 11, marginLeft: 8 }}>{option.count}</span>
          </button>
        )
      })}
    </div>
  )
}

function VehicleDetail({ listingId }: { listingId: number }) {
  const navigate = useNavigate()
  const mobile = useIsMobile()

  const [listing, setListing] = useState<VehicleListingDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  // Kept apart from loadError: a refused delete is not a reason to replace the
  // vehicle on screen with an error page.
  const [actionError, setActionError] = useState<string | null>(null)

  const [backdrops, setBackdrops] = useState<Backdrop[]>([])
  const [backdropId, setBackdropId] = useState<number | null>(null)
  const [starting, setStarting] = useState(false)
  // Reported inside the processing card rather than at the top of the page: a
  // server that cannot process is an answer to the button just pressed, and it
  // belongs next to that button.
  const [processError, setProcessError] = useState<string | null>(null)

  const [mode, setMode] = useState<GalleryMode>('processed')
  const [index, setIndex] = useState(0)

  const [imageToDelete, setImageToDelete] = useState<ListingImage | null>(null)
  const [confirmVehicleDelete, setConfirmVehicleDelete] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setListing(await api.listing(listingId))
    } catch (err) {
      setLoadError((err as Error).message)
    }
  }, [listingId])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    let cancelled = false
    api.backdrops()
      .then(rows => { if (!cancelled) setBackdrops(rows) })
      .catch(() => { /* the library is optional; processing works without one */ })
    return () => { cancelled = true }
  }, [])

  async function startProcessing() {
    setStarting(true)
    setProcessError(null)
    try {
      await api.processListing(listingId, backdropId)
      navigate(`/app/processing/${listingId}`)
    } catch (err) {
      setProcessError((err as Error).message)
    } finally {
      setStarting(false)
    }
  }

  async function deleteImage() {
    if (!imageToDelete) return
    setBusy(true)
    setActionError(null)
    try {
      await api.deleteImage(listingId, imageToDelete.id)
      setImageToDelete(null)
      // Reload rather than splicing locally: removing an original can change
      // the listing's processing status, and the count in the header with it.
      await load()
    } catch (err) {
      // The API refuses to delete an original that has already been processed,
      // and that 409 explains itself better than anything invented here.
      setActionError((err as Error).message)
      setImageToDelete(null)
    } finally {
      setBusy(false)
    }
  }

  async function deleteVehicle() {
    setBusy(true)
    setActionError(null)
    try {
      await api.deleteListing(listingId)
      navigate('/app/vehicles')
    } catch (err) {
      setActionError((err as Error).message)
      setConfirmVehicleDelete(false)
      setBusy(false)
    }
  }

  const stepper = (
    <Stepper
      steps={WORKFLOW_STEPS}
      current="review"
      onNavigate={step => {
        const href = stepHref(step.key as WorkflowStep, listingId)
        if (href) navigate(href)
      }}
    />
  )

  if (loadError) {
    return (
      <div>
        {stepper}
        <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 24px', letterSpacing: '-0.02em' }}>
          Vehicle
        </h1>
        <Alert>{loadError}</Alert>
        <SolidBtn onClick={() => navigate('/app/vehicles')}>All vehicles</SolidBtn>
      </div>
    )
  }

  if (!listing) {
    return <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>Loading…</p>
  }

  const originals = listing.images.filter(i => i.image_type === 'original')
  const processed = listing.images.filter(i => i.image_type === 'processed')
  const kept = originals.filter(i => !isExcluded(i))
  const excluded = originals.filter(isExcluded)

  // Nothing has been processed yet, so there is no processed gallery to offer.
  const activeMode: GalleryMode = processed.length ? mode : 'original'
  const gallery = activeMode === 'processed' ? processed : kept

  return (
    <div>
      {stepper}

      <div style={{
        display: 'flex', alignItems: mobile ? 'flex-start' : 'center',
        flexDirection: mobile ? 'column' : 'row',
        justifyContent: 'space-between', gap: mobile ? 12 : 24, marginBottom: 8,
      }}>
        <h1 style={{ ...serif(40), color: C.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.05 }}>
          {listing.title}
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0 }}>
          <StatusPill status={listing.processing_status} />
          <RemoveBtn
            label="Delete vehicle"
            ariaLabel={`Delete ${listing.title} and all its photographs`}
            onClick={() => setConfirmVehicleDelete(true)}
          />
        </div>
      </div>

      <p style={{ ...metaLine, margin: '0 0 28px' }}>
        {listing.stock_number ? `Stock #${listing.stock_number} · ` : ''}
        {kept.length} in the listing
        {processed.length ? ` · ${processed.length} processed` : ''}
        {excluded.length ? ` · ${excluded.length} left out` : ''}
      </p>

      {actionError && <Alert>{actionError}</Alert>}

      {originals.length === 0 ? (
        <Card style={{ padding: '48px 24px', textAlign: 'center' }}>
          <p style={{ fontFamily: SANS, fontSize: 15, color: C.inkSoft, margin: '0 0 24px' }}>
            This vehicle has no photographs yet.
          </p>
          <SolidBtn onClick={() => navigate('/app/upload')}>Add photographs</SolidBtn>
        </Card>
      ) : (
        <Card style={{ padding: mobile ? 16 : 24 }}>
          <div style={{
            display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
            gap: 16, flexWrap: 'wrap', marginBottom: 16,
          }}>
            <div>
              <p style={sectionHeading}>
                {activeMode === 'processed' ? 'Listing preview' : 'Original photographs'}
              </p>
              <p style={quietBody}>
                {activeMode === 'processed'
                  ? 'How this vehicle appears once the backdrop is applied.'
                  : 'Straight from the camera or the import, before any compositing.'}
              </p>
            </div>
            {processed.length > 0 && (
              <ModeToggle
                mode={activeMode}
                onChange={next => { setMode(next); setIndex(0) }}
                processedCount={processed.length}
                originalCount={kept.length}
              />
            )}
          </div>

          {gallery.length === 0 ? (
            <p style={{ ...quietBody, padding: '24px 0' }}>
              Every photograph on this vehicle was left out of the listing. They
              are below, with the reason for each.
            </p>
          ) : (
            <ListingGallery
              images={gallery}
              index={index}
              onIndexChange={setIndex}
              altPrefix={`${activeMode === 'processed' ? 'Processed' : 'Original'} photograph of the ${listing.title}`}
              label={activeMode === 'processed' ? 'Processed photographs' : 'Original photographs'}
              thumbMin={mobile ? 72 : 96}
              // A processed image is an output of the pipeline, not something a
              // dealer curates; reprocessing regenerates it. Removal belongs to
              // the original it came from.
              onDelete={activeMode === 'original' ? setImageToDelete : undefined}
            />
          )}
        </Card>
      )}

      {excluded.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <p style={sectionHeading}>Left out of the listing</p>
          <p style={{ ...quietBody, marginBottom: 16, maxWidth: 640 }}>
            Only an exterior shot can be cut out and placed onto a backdrop, so
            {excluded.length === 1
              ? ' this photograph was left untouched'
              : ` these ${excluded.length} photographs were left untouched`}.
            Have a look — anything that is not this vehicle can go.
          </p>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: 16,
          }}>
            {excluded.map(image => (
              <ExcludedTile
                key={image.id}
                image={image}
                onRemove={() => setImageToDelete(image)}
              />
            ))}
          </div>
        </div>
      )}

      {kept.length > 0 && (
        <Card style={{ padding: 20, marginTop: 32, maxWidth: 640 }}>
          <p style={sectionHeading}>
            {processed.length ? 'Process remaining photographs' : 'Process these photographs'}
          </p>
          <p style={{ ...quietBody, margin: '0 0 16px' }}>
            Vehicle detection, background removal, plate masking, then the chosen
            backdrop. Without one the vehicle comes back on transparency.
          </p>

          {processError && <Alert>{processError}</Alert>}

          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
            <label style={{
              fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
              textTransform: 'uppercase',
            }}>
              Backdrop
              <select
                value={backdropId ?? ''}
                onChange={e => setBackdropId(e.target.value ? Number(e.target.value) : null)}
                style={{
                  display: 'block', marginTop: 5,
                  fontFamily: SANS, fontSize: 14, color: C.ink, background: C.paper,
                  border: `1px solid ${C.lineStrong}`, borderRadius: RADIUS_CONTROL,
                  padding: '10px 14px', minWidth: 220, textTransform: 'none',
                  letterSpacing: 'normal',
                }}
              >
                <option value="">No backdrop (transparent)</option>
                {backdrops.map(backdrop => (
                  <option key={backdrop.id} value={backdrop.id}>{backdrop.name}</option>
                ))}
              </select>
            </label>
            <SolidBtn onClick={startProcessing} disabled={starting}>
              {starting ? 'Starting…' : 'Start processing'}
            </SolidBtn>
          </div>

          {backdrops.length === 0 && (
            <p style={{ ...quietBody, marginTop: 12 }}>
              Your backdrop library is empty — add one under Backdrops to composite
              onto a scene.
            </p>
          )}
        </Card>
      )}

      <div style={{ marginTop: 32 }}>
        <SolidBtn onClick={() => navigate('/app/vehicles')}>All vehicles</SolidBtn>
      </div>

      {imageToDelete && (
        <ConfirmDialog
          title="Remove this photograph?"
          body={
            <>
              <strong style={{ color: C.ink, fontWeight: 500 }}>
                {imageToDelete.original_filename}
              </strong>{' '}
              is deleted from storage as well as from this vehicle. It cannot be
              recovered, and re-uploading it is the only way back.
              {processed.length > 0 && (
                // Said before the attempt rather than after it: the database
                // holds a processing run against every photograph that has been
                // through the pipeline, and refuses to orphan it.
                <> A photograph that has already been processed will be refused
                  — its processing record still points at the file.</>
              )}
            </>
          }
          confirmLabel="Remove photograph"
          busy={busy}
          onConfirm={() => void deleteImage()}
          onCancel={() => setImageToDelete(null)}
        />
      )}

      {confirmVehicleDelete && (
        <ConfirmDialog
          title={`Delete ${listing.title}?`}
          body={
            <>
              The vehicle and all {listing.images.length} of its
              {listing.images.length === 1 ? ' image' : ' images'} — originals and
              processed alike — are deleted from storage. This cannot be undone.
              {processed.length > 0 && (
                <> A vehicle that has been through the pipeline may be refused:
                  its processing runs still reference these files.</>
              )}
            </>
          }
          confirmLabel="Delete vehicle"
          busy={busy}
          onConfirm={() => void deleteVehicle()}
          onCancel={() => setConfirmVehicleDelete(false)}
        />
      )}
    </div>
  )
}

export default function ResultsView() {
  const { listingId } = useParams()

  if (!listingId) return <VehiclesList />

  const id = Number(listingId)
  if (!Number.isInteger(id) || id <= 0) {
    return (
      <div>
        <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 24px', letterSpacing: '-0.02em' }}>
          Vehicle
        </h1>
        <Alert>“{listingId}” is not a vehicle reference.</Alert>
      </div>
    )
  }

  // Keyed on the id so moving between two vehicles resets the gallery rather
  // than showing photograph seven of a car that only has three.
  return <VehicleDetail key={id} listingId={id} />
}
