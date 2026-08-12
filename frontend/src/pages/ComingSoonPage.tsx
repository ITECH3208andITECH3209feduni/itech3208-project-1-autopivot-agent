// The public face until the product has something real to show.
//
// The full landing page makes claims the pipeline cannot yet demonstrate — its
// configurator shows the same photograph for every backdrop, and the hero
// promises angle-matched backdrops that nothing computes. Rather than publish
// that, this page says less and means it. The landing page stays reachable at
// /preview through the toggle.
//
// Dark ground, per the guidelines: light carries chrome, dark carries
// photographs. There are no photographs yet, and an empty light page would read
// as broken where an empty dark one reads as deliberate.

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import LoginModal from '../components/LoginModal'
import PreviewToggle from '../components/PreviewToggle'
import { C, MONO, RADIUS_CONTROL, SANS, serif } from '../design'

export default function ComingSoonPage() {
  const [showLogin, setShowLogin] = useState(false)
  const navigate = useNavigate()

  return (
    <div style={{
      minHeight: '100vh', background: C.ink,
      display: 'flex', flexDirection: 'column',
    }}>
      {showLogin && (
        <LoginModal
          onClose={() => setShowLogin(false)}
          onSuccess={() => { setShowLogin(false); navigate('/app') }}
          onSwitchToDemo={() => setShowLogin(false)}
        />
      )}

      <header style={{
        padding: '24px 32px', display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', gap: 24,
      }}>
        <span style={{ ...serif(20), color: C.bone, letterSpacing: '-0.01em' }}>
          AutoPivot Agent
        </span>
        <button
          onClick={() => setShowLogin(true)}
          style={{
            fontFamily: SANS, fontSize: 14, fontWeight: 500, color: C.bone,
            background: 'none', border: '1px solid rgba(226,222,214,0.25)',
            borderRadius: RADIUS_CONTROL, padding: '8px 18px', cursor: 'pointer',
            transition: 'background 0.15s, border-color 0.15s',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'rgba(245,242,236,0.08)'
            e.currentTarget.style.borderColor = 'rgba(226,222,214,0.45)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'none'
            e.currentTarget.style.borderColor = 'rgba(226,222,214,0.25)'
          }}
        >
          Log in
        </button>
      </header>

      <main style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        padding: '48px 32px', textAlign: 'center',
      }}>
        <div style={{
          fontFamily: MONO, fontSize: 11, color: C.bone, opacity: 0.45,
          letterSpacing: '0.14em', textTransform: 'uppercase', marginBottom: 28,
        }}>
          Australia &amp; New Zealand
        </div>

        <h1 style={{
          ...serif(56), color: C.bone, margin: '0 0 24px',
          lineHeight: 1.05, letterSpacing: '-0.02em', maxWidth: 720,
        }}>
          Something is being<br />built here.
        </h1>

        <p style={{
          fontFamily: SANS, fontSize: 18, color: C.bone, opacity: 0.65,
          margin: '0 0 40px', lineHeight: 1.6, maxWidth: 480,
        }}>
          AutoPivot Agent turns raw vehicle photographs into publish-ready
          listing images. We are not ready to show it yet.
        </p>

        <div style={{
          fontFamily: MONO, fontSize: 11, color: C.bone, opacity: 0.3,
          letterSpacing: '0.1em', textTransform: 'uppercase',
        }}>
          Dealer accounts are provisioned directly
        </div>
      </main>

      <footer style={{
        padding: '24px 32px', display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', gap: 24, flexWrap: 'wrap',
        borderTop: '1px solid rgba(226,222,214,0.1)',
      }}>
        <span style={{
          fontFamily: MONO, fontSize: 11, color: C.bone, opacity: 0.4,
          letterSpacing: '0.04em',
        }}>
          © {new Date().getFullYear()} AutoPivot Agent
        </span>
        <PreviewToggle current="coming-soon" />
      </footer>
    </div>
  )
}
