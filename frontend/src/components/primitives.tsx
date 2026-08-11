// Shared UI primitives, extracted from the Figma Make export's App.tsx so every
// screen draws from one implementation and from design.ts rather than a local
// copy of the tokens.

import { useState, type CSSProperties, type ReactNode } from 'react'

import { C, CARD_SHADOW, MONO, RADIUS_CARD, RADIUS_CONTROL, SANS, serif } from '../design'

export function SolidBtn({
  children, onClick, type = 'button', full = false, disabled = false,
}: {
  children: ReactNode
  onClick?: () => void
  type?: 'button' | 'submit'
  full?: boolean
  disabled?: boolean
}) {
  const [hov, setHov] = useState(false)
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        fontFamily: SANS, fontSize: 14, fontWeight: 500, color: C.white,
        background: disabled ? C.lineStrong : hov ? C.forestLift : C.forest,
        border: 'none', borderRadius: RADIUS_CONTROL, padding: '11px 20px',
        cursor: disabled ? 'not-allowed' : 'pointer',
        width: full ? '100%' : undefined, transition: 'background 0.15s',
      }}
    >
      {children}
    </button>
  )
}

export function TextBtn({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  const [hov, setHov] = useState(false)
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        fontFamily: SANS, fontSize: 14, fontWeight: 500, color: C.ink,
        background: hov ? C.line : 'none', border: 'none', cursor: 'pointer',
        padding: '8px 16px', borderRadius: RADIUS_CONTROL, transition: 'background 0.15s',
      }}
    >
      {children}
    </button>
  )
}

const labelBase: CSSProperties = {
  fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em',
  color: C.inkSoft, display: 'block', marginBottom: 5, textTransform: 'uppercase',
}

export function Field({
  label, type = 'text', value, onChange, placeholder, error, autoComplete, disabled,
}: {
  label: string
  type?: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  error?: boolean
  autoComplete?: string
  disabled?: boolean
}) {
  const [focused, setFocused] = useState(false)
  return (
    <div>
      <label style={labelBase}>{label}</label>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        autoComplete={autoComplete}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          width: '100%', fontFamily: SANS, fontSize: 14, color: C.ink,
          background: C.paper, borderRadius: RADIUS_CONTROL, padding: '10px 14px',
          outline: 'none', boxSizing: 'border-box', transition: 'border-color 0.15s',
          // lineStrong rather than line: an input's boundary is an interactive
          // component boundary, which WCAG 1.4.11 requires to reach 3:1.
          border: `1px solid ${error ? C.rust : focused ? C.forest : C.lineStrong}`,
        }}
      />
    </div>
  )
}

export function Modal({
  onClose, children, maxWidth = 420,
}: {
  onClose: () => void
  children: ReactNode
  maxWidth?: number
}) {
  return (
    <div
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(26,26,23,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24, backdropFilter: 'blur(3px)',
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        style={{
          background: C.white, borderRadius: RADIUS_CARD, width: '100%', maxWidth,
          boxShadow: '0 8px 32px rgba(26,26,23,0.18)', overflow: 'hidden', position: 'relative',
        }}
      >
        {children}
      </div>
    </div>
  )
}

export function ModalCloseBtn({ onClose }: { onClose: () => void }) {
  return (
    <button
      onClick={onClose}
      aria-label="Close"
      style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.inkSoft, padding: 4, lineHeight: 1 }}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d="M3 3L13 13M13 3L3 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </button>
  )
}

export function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{
      background: C.white, borderRadius: RADIUS_CARD, border: `1px solid ${C.line}`,
      boxShadow: CARD_SHADOW, ...style,
    }}>
      {children}
    </div>
  )
}

export function ModalHeading({ title, subtitle, onClose }: {
  title: string
  subtitle: ReactNode
  onClose: () => void
}) {
  return (
    <div style={{ padding: '32px 32px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
      <div>
        <p style={{ ...serif(28), color: C.ink, margin: '0 0 8px', letterSpacing: '-0.01em', lineHeight: 1.2 }}>
          {title}
        </p>
        <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0, lineHeight: 1.55 }}>
          {subtitle}
        </p>
      </div>
      <ModalCloseBtn onClose={onClose} />
    </div>
  )
}

// The API's processing_status values, mapped to the design's labels.
export const STATUS_LABEL = {
  pending: 'Pending',
  processing: 'Processing',
  complete: 'Complete',
  needs_review: 'Needs review',
} as const

const STATUS_STYLE: Record<keyof typeof STATUS_LABEL, CSSProperties> = {
  pending: { color: C.inkSoft, background: 'rgba(26,26,23,0.05)' },
  // amberText, not amber: amber on amberTint measures 3.12:1 and fails body
  // text. The progress track elsewhere still uses plain amber, where 3:1 is
  // sufficient.
  processing: { color: C.amberText, background: C.amberTint },
  complete: { color: C.ink, background: 'rgba(26,26,23,0.07)' },
  needs_review: { color: C.rust, background: C.rustTint },
}

export function StatusPill({ status }: { status: keyof typeof STATUS_LABEL }) {
  return (
    <span style={{
      fontFamily: SANS, fontSize: 12, fontWeight: 500, borderRadius: 999,
      padding: '3px 10px', whiteSpace: 'nowrap', ...STATUS_STYLE[status],
    }}>
      {STATUS_LABEL[status]}
    </span>
  )
}
