import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { C, RADIUS_CONTROL, SANS, serif } from '../design'

export default function ChangePasswordPage() {
  const { changePassword } = useAuth()
  const navigate = useNavigate()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError('')
    if (newPassword.length < 12) {
      setError('Your new password must contain at least 12 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('The new passwords do not match.')
      return
    }
    setSaving(true)
    try {
      await changePassword(currentPassword, newPassword)
      navigate('/app', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Password change failed.')
    } finally {
      setSaving(false)
    }
  }

  const inputStyle = {
    width: '100%', boxSizing: 'border-box' as const, padding: '10px 12px',
    border: `1px solid ${C.line}`, borderRadius: RADIUS_CONTROL, fontFamily: SANS,
  }

  return (
    <div style={{ maxWidth: 480, margin: '60px auto', padding: 28, background: C.white, border: `1px solid ${C.line}` }}>
      <h1 style={{ ...serif(32), marginTop: 0, color: C.ink }}>Change your initial password</h1>
      <p style={{ fontFamily: SANS, color: C.inkSoft }}>
        You must choose a private password before using the platform.
      </p>
      <form onSubmit={submit} style={{ display: 'grid', gap: 16 }}>
        <label style={{ fontFamily: SANS }}>Current password<input type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} required style={inputStyle} /></label>
        <label style={{ fontFamily: SANS }}>New password<input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} required minLength={12} style={inputStyle} /></label>
        <label style={{ fontFamily: SANS }}>Confirm new password<input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} required minLength={12} style={inputStyle} /></label>
        {error && <p role="alert" style={{ color: C.rust, fontFamily: SANS, margin: 0 }}>{error}</p>}
        <button disabled={saving} style={{ padding: '11px 16px', border: 0, borderRadius: RADIUS_CONTROL, background: C.forest, color: C.white, fontFamily: SANS, cursor: 'pointer' }}>
          {saving ? 'Saving…' : 'Change password'}
        </button>
      </form>
    </div>
  )
}
