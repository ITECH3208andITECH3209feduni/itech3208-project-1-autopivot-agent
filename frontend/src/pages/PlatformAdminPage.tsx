import { useEffect, useState } from 'react'

import { ApiError, api, type Dealership, type DealershipOnboardRequest, type DealershipProvisioned } from '../api/client'
import { C, MONO, RADIUS_CONTROL, SANS, serif } from '../design'

const EMPTY_FORM: DealershipOnboardRequest = {
  name: '', location: '', contact_name: '', contact_email: '', contact_phone: '',
  admin_email: '', admin_first_name: '', admin_last_name: '',
}

export default function PlatformAdminPage() {
  const [dealerships, setDealerships] = useState<Dealership[]>([])
  const [form, setForm] = useState<DealershipOnboardRequest>(EMPTY_FORM)
  const [created, setCreated] = useState<DealershipProvisioned | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  async function load() {
    try { setDealerships(await api.platformDealerships()) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not load dealerships.') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [])

  function update(field: keyof DealershipOnboardRequest, value: string) {
    setForm(current => ({ ...current, [field]: value }))
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true); setError(''); setCreated(null)
    try {
      const result = await api.onboardDealership(form)
      setCreated(result); setForm(EMPTY_FORM); await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Dealership onboarding failed.')
    } finally { setSaving(false) }
  }

  const inputStyle = {
    width: '100%', boxSizing: 'border-box' as const, padding: '9px 11px',
    border: `1px solid ${C.line}`, borderRadius: RADIUS_CONTROL,
    fontFamily: SANS, fontSize: 14, marginTop: 5,
  }
  const labelStyle = { fontFamily: SANS, fontSize: 13, color: C.inkSoft }

  return (
    <div>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ ...serif(38), color: C.ink, margin: '0 0 6px' }}>Dealership administration</h1>
        <p style={{ fontFamily: SANS, color: C.inkSoft, margin: 0 }}>Create dealerships and provision their first administrator account.</p>
      </div>
      {error && <p role="alert" style={{ padding: 12, color: C.rust, background: C.white, border: `1px solid ${C.rust}`, fontFamily: SANS }}>{error}</p>}
      {created && (
        <div role="status" style={{ padding: 18, marginBottom: 24, background: C.white, border: `1px solid ${C.forest}` }}>
          <strong style={{ fontFamily: SANS, color: C.forest }}>{created.dealership.name} was created.</strong>
          <p style={{ fontFamily: SANS, marginBottom: 6 }}>Hand these credentials to the dealership securely. The password is only shown here:</p>
          <div style={{ fontFamily: MONO, fontSize: 13 }}>{created.administrator.email} · {created.initial_password}</div>
        </div>
      )}
      <section style={{ padding: 24, marginBottom: 30, background: C.white, border: `1px solid ${C.line}` }}>
        <h2 style={{ ...serif(26), marginTop: 0, color: C.ink }}>New dealership</h2>
        <form onSubmit={submit} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
          <label style={labelStyle}>Dealership name<input required value={form.name} onChange={e => update('name', e.target.value)} style={inputStyle} /></label>
          <label style={labelStyle}>Location<input required value={form.location} onChange={e => update('location', e.target.value)} style={inputStyle} /></label>
          <label style={labelStyle}>Contact name<input required value={form.contact_name} onChange={e => update('contact_name', e.target.value)} style={inputStyle} /></label>
          <label style={labelStyle}>Contact email<input required type="email" value={form.contact_email} onChange={e => update('contact_email', e.target.value)} style={inputStyle} /></label>
          <label style={labelStyle}>Contact phone<input required value={form.contact_phone} onChange={e => update('contact_phone', e.target.value)} style={inputStyle} /></label>
          <label style={labelStyle}>Administrator email<input required type="email" value={form.admin_email} onChange={e => update('admin_email', e.target.value)} style={inputStyle} /></label>
          <label style={labelStyle}>Administrator first name<input required value={form.admin_first_name} onChange={e => update('admin_first_name', e.target.value)} style={inputStyle} /></label>
          <label style={labelStyle}>Administrator last name<input required value={form.admin_last_name} onChange={e => update('admin_last_name', e.target.value)} style={inputStyle} /></label>
          <div style={{ display: 'flex', alignItems: 'end' }}><button disabled={saving} style={{ width: '100%', padding: '10px 14px', border: 0, borderRadius: RADIUS_CONTROL, background: C.forest, color: C.white, fontFamily: SANS, cursor: 'pointer' }}>{saving ? 'Creating…' : 'Create dealership'}</button></div>
        </form>
      </section>
      <section>
        <h2 style={{ ...serif(26), color: C.ink }}>Dealerships</h2>
        {loading ? <p style={{ fontFamily: SANS }}>Loading…</p> : <div style={{ display: 'grid', gap: 10 }}>
          {dealerships.map(dealership => <article key={dealership.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 20, padding: 18, background: C.white, border: `1px solid ${C.line}` }}>
            <div><strong style={{ fontFamily: SANS, color: C.ink }}>{dealership.name}</strong><div style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft, marginTop: 4 }}>{[dealership.location, dealership.contact_name, dealership.contact_email, dealership.contact_phone].filter(Boolean).join(' · ')}</div></div>
            <div style={{ textAlign: 'right', fontFamily: MONO, fontSize: 12, color: C.inkSoft }}><div>{dealership.status}</div><div>{dealership.user_count} user{dealership.user_count === 1 ? '' : 's'}</div></div>
          </article>)}
          {!dealerships.length && <p style={{ fontFamily: SANS, color: C.inkSoft }}>No dealerships have been created.</p>}
        </div>}
      </section>
    </div>
  )
}
