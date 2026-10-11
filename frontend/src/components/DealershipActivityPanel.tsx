import { useEffect, useState } from 'react'
import { api, type DealershipActivity, type PlatformJobs } from '../api/client'
import { C, SANS, serif } from '../design'

const date = (value: string | null) => value ? new Date(value).toLocaleString() : '—'

export default function DealershipActivityPanel({ dealershipId }: { dealershipId: number }) {
  const [summary, setSummary] = useState<DealershipActivity | null>(null)
  const [jobs, setJobs] = useState<PlatformJobs | null>(null)
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(''); setJobs(null); setSummary(null)
    Promise.all([api.platformActivity(dealershipId), api.platformJobs(dealershipId, offset, status)])
      .then(([activity, page]) => { if (!cancelled) { setSummary(activity); setJobs(page) } })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load activity.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [dealershipId, offset, status, refresh])

  return (
    <section aria-label="Dealership activity" style={{ padding: 20, background: C.white, border: `1px solid ${C.line}`, fontFamily: SANS }}>
      <h3 style={{ ...serif(24), margin: '0 0 8px' }}>Activity — metadata only</h3>
      <p style={{ color: C.inkSoft, fontSize: 13 }}>Photographs, previews and downloads are unavailable to platform administrators.</p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', marginBottom: 16 }}>
        <label>Job status <select value={status} onChange={e => { setStatus(e.target.value); setOffset(0) }}>
          <option value="">All statuses</option>
          {['pending', 'processing', 'completed', 'failed'].map(s => <option key={s} value={s}>{s}</option>)}
        </select></label>
        <button type="button" disabled={loading} onClick={() => setRefresh(n => n + 1)}>Refresh</button>
      </div>
      {error && <p role="alert" style={{ color: C.rust }}>{error}</p>}
      {loading && <p role="status">Loading activity…</p>}
      {summary && <>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
          {[
            ['Active users', summary.active_users], ['Vehicles', summary.vehicle_count],
            ['Original uploads', summary.original_image_count], ['Processing jobs', summary.job_count],
          ].map(([label, value]) => <div key={label}><strong>{value}</strong><div style={{ fontSize: 13, color: C.inkSoft }}>{label}</div></div>)}
        </div>
        <p style={{ fontSize: 13 }}>{Object.entries(summary.jobs_by_status).map(([s, n]) => `${s}: ${n}`).join(' · ')}</p>
        <p style={{ fontSize: 13 }}>Latest job created: {date(summary.latest_job_at)}</p>
      </>}
      {jobs && <>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse', fontSize: 13 }}>
            <caption style={{ textAlign: 'left', marginBottom: 8 }}>Processing job metadata ({jobs.total} matching jobs)</caption>
            <thead><tr>{['Job', 'Listing', 'Type', 'Status', 'Review', 'Created', 'Started', 'Completed'].map(h => <th key={h} style={{ padding: 8, borderBottom: `1px solid ${C.line}` }}>{h}</th>)}</tr></thead>
            <tbody>{jobs.items.map(job => <tr key={job.id}>
              {[job.id, job.vehicle_listing_id, job.processing_type, job.status, job.review_state ?? '—', date(job.created_at), date(job.started_at), date(job.completed_at)].map((value, i) => <td key={i} style={{ padding: 8, borderBottom: `1px solid ${C.line}` }}>{value}</td>)}
            </tr>)}</tbody>
          </table>
        </div>
        {!jobs.items.length && <p>No processing jobs match this view.</p>}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 16 }}>
          <button type="button" disabled={loading || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 20))}>Previous</button>
          <span>{jobs.items.length ? `${offset + 1}–${offset + jobs.items.length} of ${jobs.total}` : 'No jobs on this page'}</span>
          <button type="button" disabled={loading || offset + jobs.items.length >= jobs.total} onClick={() => setOffset(n => n + 20)}>Next</button>
        </div>
      </>}
    </section>
  )
}
