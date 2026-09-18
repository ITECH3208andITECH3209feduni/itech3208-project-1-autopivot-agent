// A dealership's own team, as a platform administrator sees it — reached by
// clicking a dealership's name on PlatformAdminPage rather than a route of
// its own, since it is always looked at in the context of one dealership row
// among many, not as a destination someone bookmarks.
//
// Deliberately a separate component from DealershipUsersPage rather than a
// shared one parameterised by scope: that page already has its own tested
// behaviour for "my own dealership" against /api/dealership/users, and
// threading a second, platform-scoped API shape through it would make one
// component respondsible for two different authorisation stories. The
// markup below is intentionally close to that page's, for the same reason
// the two API route files under it are close but separate — one role, one
// scope, easy to follow on its own.

import { useEffect, useState } from 'react'

import { api, type DealershipUser, type DealershipUserCreate } from '../api/client'
import { C, MONO, RADIUS_CONTROL, SANS, serif } from '../design'

const EMPTY: DealershipUserCreate = {
  email: '', first_name: '', last_name: '', role: 'dealership_staff',
}

export default function DealershipTeamPanel({
  dealershipId, dealershipName,
}: { dealershipId: number; dealershipName: string }) {
  const [users, setUsers] = useState<DealershipUser[]>([])
  const [form, setForm] = useState<DealershipUserCreate>(EMPTY)
  const [password, setPassword] = useState<{ email: string; value: string } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    try { setUsers(await api.platformDealershipUsers(dealershipId)) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not load users.') }
    finally { setLoading(false) }
  }

  // Re-fetches if the panel is opened for a different dealership without
  // unmounting — PlatformAdminPage keeps one panel instance and swaps which
  // row it belongs to.
  useEffect(() => { void load() }, [dealershipId])

  async function add(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true); setError(''); setPassword(null)
    try {
      const created = await api.addPlatformDealershipUser(dealershipId, form)
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
        const result = await api.resetPlatformDealershipUser(dealershipId, target.id)
        setPassword({ email: target.email, value: result.initial_password })
      } else {
        await api.deactivatePlatformDealershipUser(dealershipId, target.id)
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

  return (
    <div style={{ padding: 20, background: C.paper, border: `1px solid ${C.line}`, borderTop: 0 }}>
      <h3 style={{ ...serif(22), color: C.ink, margin: '0 0 4px' }}>{dealershipName}'s team</h3>
      <p style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft, margin: '0 0 18px' }}>
        New and reset passwords must be handed over securely outside the platform.
      </p>
      {error && <p role="alert" style={{ padding: 12, color: C.rust, background: C.white, border: `1px solid ${C.rust}`, fontFamily: SANS, fontSize: 13 }}>{error}</p>}
      {password && <div role="status" style={{ padding: 16, marginBottom: 18, background: C.white, border: `1px solid ${C.forest}` }}>
        <strong style={{ fontFamily: SANS, color: C.forest, fontSize: 14 }}>Initial password for {password.email}</strong>
        <p style={{ fontFamily: SANS, fontSize: 13, margin: '8px 0' }}>Share it securely. It is shown only now; the user must change it at sign-in.</p>
        <code style={{ fontFamily: MONO, fontSize: 13 }}>{password.value}</code>
        <button type="button" onClick={() => setPassword(null)} style={{ display: 'block', marginTop: 10, fontFamily: SANS, fontSize: 13 }}>Dismiss password</button>
      </div>}
      <form onSubmit={add} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 14, marginBottom: 20 }}>
        <label style={label}>Email<input required type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} style={input} /></label>
        <label style={label}>First name<input required value={form.first_name} onChange={e => setForm(f => ({ ...f, first_name: e.target.value }))} style={input} /></label>
        <label style={label}>Last name<input required value={form.last_name} onChange={e => setForm(f => ({ ...f, last_name: e.target.value }))} style={input} /></label>
        <label style={label}>Role<select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value as DealershipUserCreate['role'] }))} style={input}>
          <option value="dealership_staff">Staff</option><option value="dealership_admin">Dealership administrator</option>
        </select></label>
        <div style={{ display: 'flex', alignItems: 'end' }}>
          <button disabled={busy} style={{ width: '100%', padding: '9px 14px', border: 0, borderRadius: RADIUS_CONTROL, background: C.forest, color: C.white, fontFamily: SANS, fontSize: 13, cursor: 'pointer' }}>Add to team</button>
        </div>
      </form>
      {loading ? <p style={{ fontFamily: SANS, fontSize: 13 }}>Loading…</p> : <div style={{ display: 'grid', gap: 8 }}>
        {users.map(target => <div key={target.id} style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 14, padding: 14, background: C.white, border: `1px solid ${C.line}` }}>
          <div style={{ fontFamily: SANS, color: C.ink, fontSize: 13 }}><strong>{target.first_name} {target.last_name}</strong>
            <div style={{ fontSize: 12, color: C.inkSoft, marginTop: 3 }}>{target.email} · {target.role === 'dealership_admin' ? 'Administrator' : 'Staff'} · {target.is_active ? 'Active' : 'Deactivated'}</div>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            {target.is_active && <button type="button" disabled={busy} onClick={() => void manage(target, 'reset')} style={{ fontFamily: SANS, fontSize: 12 }}>Reset password</button>}
            {target.is_active && <button type="button" disabled={busy} onClick={() => void manage(target, 'deactivate')} style={{ fontFamily: SANS, fontSize: 12, color: C.rust }}>Deactivate</button>}
          </div>
        </div>)}
        {!users.length && <p style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft }}>No team accounts yet.</p>}
      </div>}
    </div>
  )
}
