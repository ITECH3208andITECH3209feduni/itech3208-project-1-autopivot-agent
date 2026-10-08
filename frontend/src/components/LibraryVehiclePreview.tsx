
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  api,
  type ListingImage,
  type ProcessingJob,
  type VehicleListingDetail,
} from '../api/client'
import { C, MONO, RADIUS_CONTROL, SANS } from '../design'
import { useIsCompact } from '../useMediaQuery'
import AuthedImage from './AuthedImage'
import LibraryModal from './LibraryModal'
import { ModalHeading, SolidBtn, StatusPill } from './primitives'

type Pair = {
  original: ListingImage
  processed: ListingImage | null
  job: ProcessingJob | null
}

const humanise = (value: string) => value.replace(/_/g, ' ')

function pairImages(
  detail: VehicleListingDetail,
  jobs: ProcessingJob[] | null,
): Pair[] {
  const originals = detail.images.filter(i => i.image_type === 'original')
  const processed = detail.images.filter(i => i.image_type === 'processed')
  const byId = new Map(processed.map(image => [image.id, image]))

  return originals.map((original, index) => {
    const job = jobs?.find(j => j.input_image_id === original.id) ?? null
    const output = job?.output_image_id ? byId.get(job.output_image_id) ?? null : null

    return {
      original,
      processed: jobs === null ? processed[index] ?? null : output,
      job,
    }
  })
}

function Comparison({ pair, title, height }: { pair: Pair; title: string; height: string }) {
  const [split, setSplit] = useState(50)
  const dragging = useRef(false)

  const layer = {
    position: 'absolute' as const,
    inset: 0,
    width: '100%',
    height: '100%',
    objectFit: 'contain' as const,
    background: C.ink,
  }

  function moveTo(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    const percent = ((event.clientX - rect.left) / rect.width) * 100
    setSplit(Math.min(100, Math.max(0, percent)))
  }

  const processed = pair.processed

  return (
    <div>
      <div
        style={{
          position: 'relative', height, background: C.ink, overflow: 'hidden',
          touchAction: 'none', cursor: processed ? 'ew-resize' : 'default',
        }}
        onPointerDown={processed ? event => {
          dragging.current = true
          event.currentTarget.setPointerCapture(event.pointerId)
          moveTo(event)
        } : undefined}
        onPointerMove={processed ? event => { if (dragging.current) moveTo(event) } : undefined}
        onPointerUp={processed ? () => { dragging.current = false } : undefined}
        onPointerCancel={processed ? () => { dragging.current = false } : undefined}
      >
        <AuthedImage
          src={pair.original.image_url}
          alt={`Original photograph of ${title}`}
          style={layer}
        />

        {processed && (
          <div style={{ position: 'absolute', inset: 0, clipPath: `inset(0 0 0 ${split}%)` }}>
            <AuthedImage
              src={processed.image_url}
              alt={`${title} after processing`}
              style={layer}
            />
          </div>
        )}

        {processed && (
          <div
            aria-hidden
            style={{
              position: 'absolute', top: 0, bottom: 0, left: `${split}%`,
              width: 2, marginLeft: -1, background: C.bone,
              boxShadow: '0 0 8px rgba(26,26,23,0.5)',
            }}
          >
            <span style={{
              position: 'absolute', top: '50%', left: '50%',
              transform: 'translate(-50%, -50%)',
              width: 32, height: 32, borderRadius: '50%',
              background: C.bone, display: 'flex', alignItems: 'center',
              justifyContent: 'center',
            }}>
              <svg width="16" height="10" viewBox="0 0 16 10" fill="none">
                <path
                  d="M5 1L1 5l4 4M11 1l4 4-4 4"
                  stroke={C.ink}
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          </div>
        )}

        <span style={{
          position: 'absolute', left: 12, bottom: 12, background: C.ink,
          color: C.bone, fontFamily: MONO, fontSize: 10, letterSpacing: '0.1em',
          textTransform: 'uppercase', padding: '4px 8px', borderRadius: 4,
        }}>
          Original
        </span>
        {processed && (
          <span style={{
            position: 'absolute', right: 12, bottom: 12, background: C.ink,
            color: C.bone, fontFamily: MONO, fontSize: 10, letterSpacing: '0.1em',
            textTransform: 'uppercase', padding: '4px 8px', borderRadius: 4,
          }}>
            Processed
          </span>
        )}
      </div>

      {processed ? (
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
            style={{ flex: 1, accentColor: C.forest, cursor: 'ew-resize' }}
          />
          <button
            onClick={() => setSplit(split > 50 ? 0 : 100)}
            style={{
              fontFamily: MONO, fontSize: 10, letterSpacing: '0.08em',
              textTransform: 'uppercase', color: C.ink, background: 'none',
              border: `1px solid ${C.lineStrong}`, borderRadius: RADIUS_CONTROL,
              padding: '6px 12px', cursor: 'pointer', whiteSpace: 'nowrap',
            }}
          >
            {split > 50 ? 'Show processed' : 'Show original'}
          </button>
        </div>
      ) : (
        <p style={{
          fontFamily: SANS, fontSize: 14, color: C.inkSoft,
          margin: '16px 0 0', lineHeight: 1.6,
        }}>
          This photograph has not been processed yet, so there is nothing to
          compare it against. Open the vehicle to run it through the pipeline.
        </p>
      )}
    </div>
  )
}

export default function LibraryVehiclePreview({
  listingId, title, onClose,
}: {
  listingId: number
  title: string
  onClose: () => void
}) {
  const navigate = useNavigate()
  const compact = useIsCompact()
  const [detail, setDetail] = useState<VehicleListingDetail | null>(null)
  const [jobs, setJobs] = useState<ProcessingJob[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState(0)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.listing(listingId),
      api.listingJobs(listingId).then(summary => summary.jobs).catch(() => null),
    ])
      .then(([listing, listingJobs]) => {
        if (cancelled) return
        setDetail(listing)
        setJobs(listingJobs)
      })
      .catch((err: Error) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [listingId])

  const pairs = useMemo(() => (detail ? pairImages(detail, jobs) : []), [detail, jobs])
  const pair = pairs[selected] ?? pairs[0] ?? null
  const processedCount = pairs.filter(p => p.processed).length

  const subtitle = detail === null
    ? 'Loading…'
    : [
        detail.stock_number ? `Stock #${detail.stock_number}` : null,
        `${pairs.length} photograph${pairs.length === 1 ? '' : 's'}`,
        `${processedCount} processed`,
      ].filter(Boolean).join(' · ')

  const facts = pair?.job
    ? [
        pair.job.detected_angle ? humanise(pair.job.detected_angle) : null,
        pair.job.plate_treatment ? `plates ${humanise(pair.job.plate_treatment)}` : null,
        pair.job.review_state === 'needs_review' ? 'flagged for review' : null,
      ].filter(Boolean)
    : []

  return (
    <LibraryModal onClose={onClose} label={`Preview — ${detail?.title ?? title}`} maxWidth={1040}>
      <ModalHeading title={detail?.title ?? title} subtitle={subtitle} onClose={onClose} />

      <div style={{ padding: compact ? '20px 20px 24px' : '24px 32px 32px' }}>
        {error && (
          <div role="alert" style={{
            fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
            borderRadius: 8, padding: '12px 16px',
          }}>
            {error}
          </div>
        )}

        {!error && detail === null && (
          <div style={{
            height: compact ? 200 : 320, background: C.bone, borderRadius: RADIUS_CONTROL,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: MONO, fontSize: 11, letterSpacing: '0.1em',
            textTransform: 'uppercase', color: C.inkSoft,
          }}>
            Loading
          </div>
        )}

        {!error && detail !== null && pair === null && (
          <div style={{ padding: '32px 0', textAlign: 'center' }}>
            <p style={{ fontFamily: SANS, fontSize: 16, color: C.ink, margin: '0 0 8px' }}>
              No photographs on this vehicle yet
            </p>
            <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0, lineHeight: 1.6 }}>
              Open the vehicle to add its photographs.
            </p>
          </div>
        )}

        {!error && detail !== null && pair !== null && (
          <>
            <Comparison
              pair={pair}
              title={detail.title}
              height={compact ? 'min(38vh, 280px)' : 'min(46vh, 440px)'}
            />

            {(facts.length > 0 || pair.job?.error_message) && (
              <p style={{
                fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em',
                textTransform: 'uppercase', margin: '12px 0 0',
                color: pair.job?.error_message ? C.rust : C.inkSoft,
              }}>
                {pair.job?.error_message ?? facts.join(' · ')}
              </p>
            )}

            {pairs.length > 1 && (
              <div
                role="group"
                aria-label="Photographs on this vehicle"
                style={{
                  display: 'flex', gap: 8, overflowX: 'auto', paddingTop: 20, paddingBottom: 4,
                }}
              >
                {pairs.map((candidate, index) => {
                  const isSelected = index === selected
                  const thumb = candidate.processed ?? candidate.original
                  return (
                    <button
                      key={candidate.original.id}
                      onClick={() => setSelected(index)}
                      aria-pressed={isSelected}
                      aria-label={
                        `Photograph ${index + 1} of ${pairs.length}` +
                        (candidate.processed ? ', processed' : ', not processed yet')
                      }
                      style={{
                        flexShrink: 0, width: 84, height: 58, padding: 0, overflow: 'hidden',
                        borderRadius: 8, cursor: 'pointer', background: C.bone,
                        border: `1px solid ${isSelected ? C.forest : C.line}`,
                        boxShadow: isSelected ? `0 0 0 2px ${C.forest}` : 'none',
                        opacity: candidate.processed ? 1 : 0.65,
                      }}
                    >
                      <AuthedImage
                        src={thumb.image_url}
                        alt=""
                        style={{ width: '100%', height: '100%', display: 'block' }}
                      />
                    </button>
                  )
                })}
              </div>
            )}
          </>
        )}

        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 16, flexWrap: 'wrap', marginTop: 24,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {detail && <StatusPill status={detail.processing_status} />}
            {pairs.length > 1 && (
              <span style={{ fontFamily: MONO, fontSize: 11, color: C.inkSoft }}>
                {selected + 1} / {pairs.length}
              </span>
            )}
          </div>
          <SolidBtn onClick={() => { onClose(); navigate(`/app/vehicles/${listingId}`) }}>
            Open this vehicle
          </SolidBtn>
        </div>
      </div>
    </LibraryModal>
  )
}
