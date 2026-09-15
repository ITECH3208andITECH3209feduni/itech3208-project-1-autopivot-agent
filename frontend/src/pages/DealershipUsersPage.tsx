import { useEffect, useState } from 'react'

import { api, type DealershipUser, type DealershipUserCreate } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { C, MONO, RADIUS_CONTROL, SANS, serif } from '../design'

const EMPTY: DealershipUserCreate = {
  email: '', first_name: '', last_name: '', role: 'dealership_staff',
}

export default function DealershipUsersPage() {
  const { user: administrator } = useAuth()
  const [users, setUsers] = useState<DealershipUser[]>([])
  const [form, setForm] = useState<DealershipUserCreate>(EMPTY)
  const [password, setPassword] = useState<{ email: string; value: string } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  async function load() {
    try { setUsers(await api.dealershipUsers()) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not load users.') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [])

  async function add(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true); setError(''); setPassword(null)
    try {
      const created = await api.addDealershipUser(form)
      setPassword({ email: created.user.email, value: created.initial_password })
      setForm(EMPTY)
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not add user.') }
    finally { setBusy(false) }
  }

  async function manage(target: DealershipUser, action: 'reset' | 'deactivate') {
    if (action === 'deactivate' && !window.confirm(`Deactivate ${target.email}? They will lose access immediately.`)) return
    setBusy(true); setError(''); setPassword(null)
    try {
      if (action === 'reset') {
        const result = await api.resetDealershipUser(target.id)
        setPassword({ email: target.email, value: result.initial_password })
      } else {
        await api.deactivateDealershipUser(target.id)
      }
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : `Could not ${action} user.`) }
    finally { setBusy(false) }
  }

  const input = {
    width: '100%', boxSizing: 'border-box' as const, padding: '9px 11px', marginTop: 5,
    border: `1px solid ${C.line}`, borderRadius: RADIUS_CONTROL, fontFamily: SANS, fontSize: 14,
  }
  const label = { fontFamily: SANS, fontSize: 13, color: C.inkSoft }

  return <div>
    <h1 style={{ ...serif(38), color: C.ink, margin: '0 0 6px' }}>Team accounts</h1>
    <p style={{ fontFamily: SANS, color: C.inkSoft, margin: '0 0 28px' }}>
      Manage users at {administrator?.dealership?.name}. New and reset passwords must be handed over securely outside the platform.
    </p>
    {error && <p role="alert" style={{ padding: 12, color: C.rust, background: C.white, border: `1px solid ${C.rust}`, fontFamily: SANS }}>{error}</p>}
    {password && <div role="status" style={{ padding: 18, marginBottom: 24, background: C.white, border: `1px solid ${C.forest}` }}>
      <strong style={{ fontFamily: SANS, color: C.forest }}>Initial password for {password.email}</strong>
      <p style={{ fontFamily: SANS, margin: '8px 0' }}>Share it securely. It is shown only now; the user must change it at sign-in.</p>
      <code style={{ fontFamily: MONO }}>{password.value}</code>
      <button type="button" onClick={() => setPassword(null)} style={{ display: 'block', marginTop: 12, fontFamily: SANS }}>Dismiss password</button>
    </div>}
    <section style={{ padding: 24, background: C.white, border: `1px solid ${C.line}`, marginBottom: 30 }}>
      <h2 style={{ ...serif(26), color: C.ink, marginTop: 0 }}>Add user</h2>
      <form onSubmit={add} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 16 }}>
        <label style={label}>Email<input required type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} style={input} /></label>
        <label style={label}>First name<input required value={form.first_name} onChange={e => setForm(f => ({ ...f, first_name: e.target.value }))} style={input} /></label>
        <label style={label}>Last name<input required value={form.last_name} onChange={e => setForm(f => ({ ...f, last_name: e.target.value }))} style={input} /></label>
        <label style={label}>Role<select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value as DealershipUserCreate['role'] }))} style={input}>
          <option value="dealership_staff">Staff</option><option value="dealership_admin">Dealership administrator</option>
        </select></label>
        <button disabled={busy} style={{ padding: '10px 14px', border: 0, borderRadius: RADIUS_CONTROL, background: C.forest, color: C.white, fontFamily: SANS, cursor: 'pointer' }}>Create account</button>
      </form>
    </section>
    <section>
      <h2 style={{ ...serif(26), color: C.ink }}>Users</h2>
      {loading ? <p style={{ fontFamily: SANS }}>Loading…</p> : <div style={{ display: 'grid', gap: 10 }}>
        {users.map(target => <article key={target.id} style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 16, padding: 18, background: C.white, border: `1px solid ${C.line}` }}>
          <div style={{ fontFamily: SANS, color: C.ink }}><strong>{target.first_name} {target.last_name}</strong>
            <div style={{ fontSize: 13, color: C.inkSoft, marginTop: 4 }}>{target.email} · {target.role === 'dealership_admin' ? 'Administrator' : 'Staff'} · {target.is_active ? 'Active' : 'Deactivated'}</div>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            {target.is_active && <button type="button" disabled={busy} onClick={() => void manage(target, 'reset')} style={{ fontFamily: SANS }}>Reset password</button>}
            {target.is_active && target.id !== administrator?.id && <button type="button" disabled={busy} onClick={() => void manage(target, 'deactivate')} style={{ fontFamily: SANS, color: C.rust }}>Deactivate</button>}
          </div>
        </article>)}
        {!users.length && <p style={{ fontFamily: SANS, color: C.inkSoft }}>No team accounts yet.</p>}
      </div>}
    </section>
  </div>
}
