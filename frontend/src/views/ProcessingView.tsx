// Live progress for a listing's jobs.
//
// Polls rather than streams: a run is a handful of jobs taking seconds to
// minutes each, so a two-second poll is simpler than websockets and costs
// almost nothing. Polling stops as soon as no job is outstanding.

import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api, type ProcessingSummary } from '../api/client'
import { Card, SolidBtn, StatusPill } from '../components/primitives'
import { C, MONO, SANS, serif } from '../design'

const POLL_MS = 2000

function JobRow({ index, status, reviewState, error }: {
  index: number
  status: string
  reviewState: string | null
  error: string | null
}) {
  const label =
    status === 'failed' ? 'Failed'
      : reviewState === 'needs_review' ? 'Needs review'
        : status === 'completed' ? 'Complete'
          : status === 'processing' ? 'Processing'
            : 'Queued'

  const pill =
    status === 'failed' || reviewState === 'needs_review' ? 'needs_review'
      : status === 'completed' ? 'complete'
        : status === 'processing' ? 'processing'
          : 'pending'

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 16, padding: '12px 20px',
      borderTop: index > 0 ? `1px solid ${C.line}` : 'none',
    }}>
      <span style={{ fontFamily: MONO, fontSize: 11, color: C.inkSoft, width: 40 }}>
        {String(index + 1).padStart(2, '0')}
      </span>
      <span style={{ flex: 1, fontFamily: SANS, fontSize: 14, color: C.ink }}>
        {label}
        {error && (
          <span style={{ display: 'block', fontFamily: SANS, fontSize: 13, color: C.inkSoft, marginTop: 2 }}>
            {error}
          </span>
        )}
      </span>
      <StatusPill status={pill as 'pending' | 'processing' | 'complete' | 'needs_review'} />
    </div>
  )
}

export default function ProcessingView() {
  const { listingId } = useParams()
  const navigate = useNavigate()
  const [summary, setSummary] = useState<ProcessingSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    if (!listingId) return
    let cancelled = false

    async function poll() {
      try {
        const next = await api.listingJobs(Number(listingId))
        if (cancelled) return
        setSummary(next)

        const outstanding = next.jobs.some(
          j => j.status === 'pending' || j.status === 'processing',
        )
        if (outstanding) {
          timer.current = window.setTimeout(poll, POLL_MS)
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message)
      }
    }

    void poll()
    return () => {
      cancelled = true
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [listingId])

  if (!listingId) {
    return (
      <div>
        <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 24px', letterSpacing: '-0.02em' }}>Processing</h1>
        <Card style={{ padding: '48px 24px', textAlign: 'center' }}>
          <p style={{ fontFamily: SANS, fontSize: 15, color: C.inkSoft, margin: '0 0 24px' }}>
            Choose a vehicle to see its progress.
          </p>
          <SolidBtn onClick={() => navigate('/app/vehicles')}>All vehicles</SolidBtn>
        </Card>
      </div>
    )
  }

  const done = summary ? summary.completed + summary.failed : 0
  const total = summary?.total ?? 0
  const percent = total ? Math.round((done / total) * 100) : 0
  const finished = summary !== null && done === total && total > 0

  return (
    <div>
      <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 8px', letterSpacing: '-0.02em', lineHeight: 1 }}>
        Processing
      </h1>
      <p style={{
        fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
        textTransform: 'uppercase', margin: '0 0 32px',
      }}>
        {total ? `${done} of ${total} complete` : 'No jobs queued'}
      </p>

      {error && (
        <div role="alert" style={{
          fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
          borderRadius: 8, padding: '12px 16px', marginBottom: 24,
        }}>
          {error}
        </div>
      )}

      {total > 0 && (
        <div style={{
          height: 4, borderRadius: 999, background: C.line,
          overflow: 'hidden', marginBottom: 24, maxWidth: 640,
        }}>
          {/* Plain amber on the track: 3:1 is sufficient for a non-text
              boundary, which is why the pill uses the darker amberText and
              this does not. */}
          <div style={{
            width: `${percent}%`, height: '100%', background: C.amber,
            transition: 'width 0.4s ease',
          }} />
        </div>
      )}

      {summary && summary.jobs.length > 0 && (
        <Card style={{ overflow: 'hidden', maxWidth: 640 }}>
          {summary.jobs.map((job, i) => (
            <JobRow
              key={job.id}
              index={i}
              status={job.status}
              reviewState={job.review_state}
              error={job.error_message}
            />
          ))}
        </Card>
      )}

      {finished && (
        <div style={{ marginTop: 24, display: 'flex', gap: 12 }}>
          <SolidBtn onClick={() => navigate(`/app/vehicles/${listingId}`)}>
            View results
          </SolidBtn>
        </div>
      )}
    </div>
  )
}
