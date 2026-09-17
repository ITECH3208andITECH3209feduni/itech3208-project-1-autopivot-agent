// Login, wired to POST /auth/login.
//
// The Figma Make export called onSuccess() whenever both fields were non-empty.
// This talks to the real endpoint and surfaces what it actually returns.

import { useState } from 'react'

import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { C, SANS } from '../design'
import { Field, Modal, ModalHeading, SolidBtn } from './primitives'

export default function LoginModal({
  onClose, onSuccess, onSwitchToDemo,
}: {
  onClose: () => void
  onSuccess: () => void
  onSwitchToDemo: () => void
}) {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim() || !password) {
      setError('Enter your email and password.')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      await login(email.trim(), password)
      onSuccess()
    } catch (err) {
      // The server returns one generic message for a wrong password, an unknown
      // email and a deactivated account alike, so it cannot be used to work out
      // which addresses have accounts. Whatever it says is shown verbatim.
      setError(
        err instanceof ApiError ? err.message : 'Something went wrong. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal onClose={onClose}>
      <ModalHeading
        title="Log in"
        onClose={onClose}
        subtitle={
          <>
            Dealer accounts are provisioned by AutoPivot. New here?{' '}
            <button
              type="button"
              onClick={() => { onClose(); onSwitchToDemo() }}
              style={{
                fontFamily: SANS, fontSize: 14, color: C.forest, background: 'none',
                border: 'none', cursor: 'pointer', padding: 0, textDecoration: 'underline',
              }}
            >
              Request a demo
            </button>
          </>
        }
      />

      <div style={{ padding: 32 }}>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {error && (
            <p
              role="alert"
              style={{
                fontFamily: SANS, fontSize: 13, color: C.rust, margin: 0,
                padding: '10px 14px', background: C.rustTint, borderRadius: 8,
              }}
            >
              {error}
            </p>
          )}

          <Field
            label="Email" type="email" value={email} autoComplete="username"
            onChange={v => { setEmail(v); setError(null) }}
            placeholder="you@dealership.co.nz" error={!!error} disabled={submitting}
          />

          <div>
            <Field
              label="Password" type="password" value={password} autoComplete="current-password"
              onChange={v => { setPassword(v); setError(null) }}
              placeholder="••••••••" error={!!error} disabled={submitting}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
              {/* No reset flow exists yet — there is no designed screen for it
                  and no mail transport on the backend. Left visible so the
                  layout matches the design, but honest about being inert. */}
              <span
                title="Password reset is not available yet — contact AutoPivot support."
                style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft, cursor: 'default' }}
              >
                Forgot password?
              </span>
            </div>
          </div>

          <SolidBtn type="submit" full disabled={submitting}>
            {submitting ? 'Signing in…' : 'Log in'}
          </SolidBtn>
        </form>
      </div>
    </Modal>
  )
}
