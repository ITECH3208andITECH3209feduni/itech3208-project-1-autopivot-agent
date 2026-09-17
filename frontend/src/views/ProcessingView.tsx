// Step two of the workflow: watching a run happen.
//
// Polls rather than streams: a run is a handful of jobs taking seconds to
// minutes each, so a two-second poll is simpler than websockets and costs
// almost nothing. Polling stops as soon as no job is outstanding.
//
// What changed is what the poll is used for. The screen used to be a flat list
// of rows reading "Complete", which is the least a progress screen can say. A
// dealer waiting on eighteen photographs wants to know which one is being
// worked on, what came back for it, and — when something needs them — whether
// it needs a decision or a fix. So each job is a card with the photograph on
// it, the run gets a summary that reads like a report rather than a spinner,
// and finishing hands over to Review instead of leaving the dealer to find it.

import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  api,
  type Backdrop,
  type ListingImage,
  type ProcessingSummary,
  type VehicleListingDetail,
} from '../api/client'
import {
  WORKFLOW_MOTION_CSS,
  WorkflowJobCard,
} from '../components/WorkflowJobCard'
import { Card, SolidBtn, Stepper, TextBtn, type Step } from '../components/primitives'
import { C, MONO, SANS, serif } from '../design'
import { WORKFLOW_STEPS, stepHref, type WorkflowStep } from '../workflow'

const POLL_MS = 2000

function Tally({ value, label, tone }: { value: number; label: string; tone: string }) {
  return (
    <div>
      <p style={{
        fontFamily: MONO, fontSize: 22, margin: '0 0 2px', lineHeight: 1,
        // The numeral carries the colour, but the label under it carries the
        // meaning — nothing here depends on telling forest from rust.
        color: value === 0 ? C.inkSoft : tone,
      }}>
        {value}
      </p>
      <p style={{
        fontFamily: SANS, fontSize: 13, color: C.inkSoft, margin: 0, whiteSpace: 'nowrap',
      }}>
        {label}
      </p>
    </div>
  )
}

export default function ProcessingView() {
  const { listingId } = useParams()
  const navigate = useNavigate()
  // Only treated as a listing id if it genuinely is one. /app/processing/abc
  // would otherwise poll the API with NaN in the path every two seconds.
  const parsed = listingId ? Number(listingId) : Number.NaN
  const id = Number.isInteger(parsed) ? parsed : null

  const [summary, setSummary] = useState<ProcessingSummary | null>(null)
  const [listing, setListing] = useState<VehicleListingDetail | null>(null)
  const [backdrops, setBackdrops] = useState<Backdrop[]>([])
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    if (id === null) return
    const target = id
    let cancelled = false
    // Whether anything was ever outstanding, so a run that was already over
    // when the screen opened does not fetch the listing twice.
    let sawOutstanding = false

    // The originals are where the thumbnails and filenames come from. The
    // classifier writes its verdict onto the image rather than the job, so the
    // listing is read again once the run settles — that is what lets a
    // set-aside photograph say "this is an advertisement banner".
    async function loadListing() {
      try {
        const next = await api.listing(target)
        if (!cancelled) setListing(next)
      } catch {
        // Thumbnails are a courtesy; the jobs still report themselves without
        // the listing, so this failure is not worth an alert.
      }
    }

    async function poll() {
      try {
        const next = await api.listingJobs(target)
        if (cancelled) return
        setSummary(next)
        setError(null)

        const outstanding = next.jobs.some(
          j => j.status === 'pending' || j.status === 'processing',
        )
        if (outstanding) {
          sawOutstanding = true
          timer.current = window.setTimeout(() => void poll(), POLL_MS)
        } else if (sawOutstanding) {
          void loadListing()
        }
      } catch (err) {
        if (cancelled) return
        setError((err as Error).message)
        // One dropped request should not freeze a run someone is watching, so
        // the poll keeps going while there is still work outstanding and the
        // next success clears the message. Once nothing is outstanding there is
        // nothing to catch up on, and retrying forever would be noise.
        if (sawOutstanding) timer.current = window.setTimeout(() => void poll(), POLL_MS)
      }
    }

    void loadListing()
    void poll()
    api.backdrops()
      .then(next => { if (!cancelled) setBackdrops(next) })
      .catch(() => { /* naming the backdrop is a nicety, not the point */ })

    return () => {
      cancelled = true
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [id])

  function goToStep(step: Step) {
    // Clicking the step you are on should do nothing rather than push another
    // copy of this page onto the history stack.
    if (step.key === 'process') return
    const href = stepHref(step.key as WorkflowStep, id)
    if (href) navigate(href)
  }

  if (id === null) {
    return (
      <div>
        <Stepper steps={WORKFLOW_STEPS} current="process" onNavigate={goToStep} />
        <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 24px', letterSpacing: '-0.02em', lineHeight: 1 }}>
          Processing
        </h1>
        <Card style={{ padding: '48px 24px', textAlign: 'center' }}>
          <p style={{ fontFamily: SANS, fontSize: 15, color: C.inkSoft, margin: '0 0 24px' }}>
            Processing belongs to a vehicle. Choose one to see its progress, or
            add a new vehicle to start a run.
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <SolidBtn onClick={() => navigate('/app/upload')}>Add a vehicle</SolidBtn>
            <TextBtn onClick={() => navigate('/app/vehicles')}>All vehicles</TextBtn>
          </div>
        </Card>
      </div>
    )
  }

  const jobs = summary?.jobs ?? []
  const total = summary?.total ?? 0
  const done = summary ? summary.completed + summary.failed : 0
  const failed = summary?.failed ?? 0
  const needsPerson = summary?.needs_review ?? 0
  // `completed` counts every job that ran to the end, including the ones the
  // pipeline handed back for a person to look at.
  const ready = summary ? summary.completed - summary.needs_review : 0
  const waiting = Math.max(total - done, 0)
  const percent = total ? Math.round((done / total) * 100) : 0
  const finished = summary !== null && total > 0 && done === total

  const imagesById = new Map<number, ListingImage>(
    (listing?.images ?? []).map(image => [image.id, image]),
  )

  // Every job in a run carries the same backdrop, so it is named once here
  // rather than repeated on every card.
  const backdropId = jobs.find(j => j.backdrop_id !== null)?.backdrop_id ?? null
  const backdropName = backdrops.find(b => b.id === backdropId)?.name ?? null

  const statusLine =
    summary === null ? 'Checking this run'
      : total === 0 ? 'Nothing queued yet'
        : [
          `${done} of ${total} photograph${total === 1 ? '' : 's'} finished`,
          needsPerson ? `${needsPerson} need${needsPerson === 1 ? 's' : ''} a person` : null,
          failed ? `${failed} failed` : null,
        ].filter(Boolean).join(' · ')

  const headline =
    summary === null ? 'Looking up this run…'
      : total === 0 ? 'Nothing has been queued for this vehicle'
        : !finished ? `Working through ${total} photograph${total === 1 ? '' : 's'}`
          : failed === 0 && needsPerson === 0 ? `All ${total} photograph${total === 1 ? '' : 's'} are ready`
            : 'Finished, with some to look at'

  // Said once, in full sentences, rather than assembled inside the markup
  // where the grammar of "1 was" versus "2 were" gets lost.
  const outstandingParts = [
    needsPerson > 0
      ? `${needsPerson} ${needsPerson === 1 ? 'was' : 'were'} set aside for a person to decide on`
      : null,
    failed > 0
      ? `${failed} could not be processed at all`
      : null,
  ].filter(Boolean)

  const finishedNote = outstandingParts.length === 0
    ? 'Every photograph came back with a vehicle on the backdrop. Review is where you check them and publish.'
    : `The finished photographs are ready to publish. ${outstandingParts.join(', and ')} — shown below, and waiting for you on Review.`

  const reviewHref = stepHref('review', id) ?? '/app/vehicles'

  return (
    <div>
      {/* The workflow's one animation, declared once for the whole screen. */}
      <style>{WORKFLOW_MOTION_CSS}</style>

      <Stepper steps={WORKFLOW_STEPS} current="process" onNavigate={goToStep} />

      <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 8px', letterSpacing: '-0.02em', lineHeight: 1.05 }}>
        {listing?.title ?? 'Processing'}
      </h1>
      {/* A live region: the count changes under the dealer while they watch,
          and a screen reader should hear it rather than have to go looking. */}
      <p
        role="status"
        aria-live="polite"
        style={{
          fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
          textTransform: 'uppercase', margin: '0 0 28px',
        }}
      >
        {statusLine}
      </p>

      {error && (
        <div role="alert" style={{
          fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
          borderRadius: 8, padding: '12px 16px', marginBottom: 24, lineHeight: 1.6,
        }}>
          {error}
        </div>
      )}

      <Card style={{ padding: 24, marginBottom: 28 }}>
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: '4px 24px',
          alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 18,
        }}>
          <p style={{ fontFamily: SANS, fontSize: 18, fontWeight: 500, color: C.ink, margin: 0 }}>
            {headline}
          </p>
          {jobs.length > 0 && (
            <p style={{
              fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
              textTransform: 'uppercase', margin: 0,
            }}>
              {backdropName ? `onto ${backdropName}` : 'no backdrop — transparent'}
            </p>
          )}
        </div>

        {total > 0 && (
          <>
            <div
              role="progressbar"
              aria-label="Photographs finished"
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={done}
              aria-valuetext={statusLine}
              style={{ height: 6, borderRadius: 999, background: C.line, overflow: 'hidden' }}
            >
              {/* Plain amber on the track: 3:1 is sufficient for a non-text
                  boundary, which is why the pill uses the darker amberText and
                  this does not. It turns forest when the run is over, matching
                  the completed step in the bar above. */}
              <div style={{
                width: `${percent}%`, height: '100%',
                background: finished ? C.forest : C.amber,
                transition: 'width 0.4s ease, background 0.4s ease',
              }} />
            </div>

            <div style={{
              display: 'flex', flexWrap: 'wrap', gap: '16px 32px', marginTop: 20,
            }}>
              <Tally value={ready} label="Ready" tone={C.forest} />
              <Tally value={needsPerson} label="Need a person" tone={C.rust} />
              <Tally value={failed} label="Failed" tone={C.rust} />
              <Tally value={waiting} label="Still to go" tone={C.amberText} />
            </div>
          </>
        )}

        {summary !== null && total === 0 && (
          <div>
            <p style={{
              fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 20px',
              lineHeight: 1.6, maxWidth: 620,
            }}>
              Nothing has been sent to the pipeline for this vehicle yet. Open it
              to add photographs, pick a backdrop and start a run — or start one
              from the beginning by adding a new vehicle.
            </p>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
              <SolidBtn onClick={() => navigate(`/app/vehicles/${id}`)}>Open the vehicle</SolidBtn>
              <TextBtn onClick={() => navigate('/app/upload')}>Add a vehicle</TextBtn>
            </div>
          </div>
        )}

        {total > 0 && !finished && (
          <p style={{
            fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '20px 0 0',
            lineHeight: 1.6, maxWidth: 620,
          }}>
            Each photograph is cut out, its plates are covered and it is placed
            onto the backdrop. The work runs on the server, so you can leave this
            page and come back — this list catches itself up every couple of
            seconds.
          </p>
        )}

        {finished && (
          <div style={{ marginTop: 22 }}>
            <p style={{
              fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 16px',
              lineHeight: 1.6, maxWidth: 620,
            }}>
              {finishedNote}
            </p>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
              <SolidBtn onClick={() => navigate(reviewHref)}>
                Review {total} photograph{total === 1 ? '' : 's'}
              </SolidBtn>
              <TextBtn onClick={() => navigate('/app/vehicles')}>All vehicles</TextBtn>
            </div>
          </div>
        )}
      </Card>

      {jobs.length > 0 && (
        // auto-fill, so the same grid gives a laptop two columns and a 32-inch
        // monitor six without either being told how many to draw.
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 16,
        }}>
          {jobs.map((job, i) => (
            <WorkflowJobCard
              key={job.id}
              job={job}
              index={i}
              image={imagesById.get(job.input_image_id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
