// A designed 404, replacing the catch-all redirect to "/".
//
// Silently redirecting is worse than it looks: a mistyped or stale link lands
// the user somewhere plausible with no indication anything went wrong, and a
// signed-in user gets dropped to the public page as if they had been signed
// out. This says what happened and offers the two places worth going.

import { useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { SolidBtn, TextBtn } from '../components/primitives'
import { C, MONO, SANS, serif } from '../design'

export default function NotFoundPage() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user } = useAuth()

  return (
    <div style={{
      minHeight: '100vh', background: C.bone,
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: '48px 24px', textAlign: 'center',
    }}>
      <div style={{
        fontFamily: MONO, fontSize: 11, letterSpacing: '0.14em',
        textTransform: 'uppercase', color: C.inkSoft, marginBottom: 20,
      }}>
        404 — Page not found
      </div>

      <h1 style={{
        ...serif(40), color: C.ink, margin: '0 0 16px',
        letterSpacing: '-0.02em', lineHeight: 1.1, maxWidth: 560,
      }}>
        That page isn't here.
      </h1>

      <p style={{
        fontFamily: SANS, fontSize: 16, color: C.inkSoft,
        margin: '0 0 8px', lineHeight: 1.6, maxWidth: 460,
      }}>
        The link may be out of date, or the address may have a typo in it.
      </p>

      <p style={{
        fontFamily: MONO, fontSize: 12, color: C.inkSoft, opacity: 0.7,
        margin: '0 0 40px', wordBreak: 'break-all', maxWidth: 460,
      }}>
        {pathname}
      </p>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'center' }}>
        {/* Signed-in users are sent back into the application rather than out
            to the public page, which would read as having been logged out. */}
        {user ? (
          <SolidBtn onClick={() => navigate('/app')}>Back to Overview</SolidBtn>
        ) : (
          <SolidBtn onClick={() => navigate('/')}>Back to the start</SolidBtn>
        )}
        {user && <TextBtn onClick={() => navigate('/app/vehicles')}>Vehicles</TextBtn>}
      </div>
    </div>
  )
}
