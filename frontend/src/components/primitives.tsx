// Shared UI primitives, extracted from the Figma Make export's App.tsx so every
// screen draws from one implementation and from design.ts rather than a local
// copy of the tokens.

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

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

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'

export function Modal({
  onClose, children, maxWidth = 420,
}: {
  onClose: () => void
  children: ReactNode
  maxWidth?: number
}) {
  const dialog = useRef<HTMLDivElement>(null)

  // A dialog that does not manage focus is only nominally accessible: it opens
  // with focus still behind it, Tab walks out into the page underneath, Escape
  // does nothing, and closing it drops focus to <body> so the next Tab starts
  // from the top of the document. All four are fixed here rather than in each
  // caller, because every one of them would otherwise have to remember.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null

    const first = dialog.current?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? dialog.current)?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !dialog.current) return

      const focusable = Array.from(
        dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter(el => el.offsetParent !== null)
      if (focusable.length === 0) {
        event.preventDefault()
        return
      }

      const edge = event.shiftKey ? focusable[0] : focusable[focusable.length - 1]
      if (document.activeElement === edge || !dialog.current.contains(document.activeElement)) {
        event.preventDefault()
        ;(event.shiftKey ? focusable[focusable.length - 1] : focusable[0]).focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    // The page behind must not scroll while a dialog is over it.
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      document.body.style.overflow = previousOverflow
      opener?.focus?.()
    }
  }, [onClose])

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
        ref={dialog}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        style={{
          background: C.white, borderRadius: RADIUS_CARD, width: '100%', maxWidth,
          boxShadow: '0 8px 32px rgba(26,26,23,0.18)', overflow: 'hidden', position: 'relative',
          outline: 'none',
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

// ── Shared pieces added for the workflow rework ───────────────────────────────

/** A destructive action needs a deliberate second step, not a browser confirm(). */
export function ConfirmDialog({
  title, body, confirmLabel = 'Delete', busy = false, onConfirm, onCancel,
}: {
  title: string
  body: ReactNode
  confirmLabel?: string
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Modal onClose={busy ? () => {} : onCancel} maxWidth={440}>
      <div style={{ padding: 24 }}>
        <p style={{ ...serif(22), color: C.ink, margin: '0 0 8px', letterSpacing: '-0.01em' }}>
          {title}
        </p>
        <div style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, lineHeight: 1.6, margin: '0 0 24px' }}>
          {body}
        </div>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          <button
            onClick={onCancel}
            disabled={busy}
            style={{
              fontFamily: SANS, fontSize: 14, color: C.ink, background: 'none',
              border: `1px solid ${C.lineStrong}`, borderRadius: RADIUS_CONTROL,
              padding: '10px 18px', cursor: busy ? 'not-allowed' : 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            style={{
              fontFamily: SANS, fontSize: 14, fontWeight: 500, color: C.white,
              background: C.rust, border: 'none', borderRadius: RADIUS_CONTROL,
              padding: '10px 18px', cursor: busy ? 'not-allowed' : 'pointer',
              opacity: busy ? 0.6 : 1,
            }}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}

export type Step = { key: string; label: string; href?: string }

/**
 * Where you are in Upload → Process → Review.
 *
 * Rendered as an ordered list because that is what it is; a screen reader
 * announcing "step 2 of 3" is the whole point of the component.
 */
export function Stepper({
  steps, current, onNavigate,
}: {
  steps: Step[]
  current: string
  onNavigate?: (step: Step, index: number) => void
}) {
  const currentIndex = steps.findIndex(s => s.key === current)

  return (
    <nav aria-label="Progress" style={{ marginBottom: 32 }}>
      <ol style={{
        display: 'flex', alignItems: 'center', gap: 0,
        listStyle: 'none', margin: 0, padding: 0, flexWrap: 'wrap',
      }}>
        {steps.map((step, i) => {
          const done = i < currentIndex
          const active = i === currentIndex
          // Only steps already reached are navigable: jumping ahead to Review
          // before anything has processed lands on an empty screen.
          const reachable = i <= currentIndex && !!onNavigate

          return (
            <li key={step.key} style={{ display: 'flex', alignItems: 'center' }}>
              <button
                onClick={reachable ? () => onNavigate?.(step, i) : undefined}
                disabled={!reachable}
                aria-current={active ? 'step' : undefined}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  background: 'none', border: 'none', padding: '4px 2px',
                  cursor: reachable && !active ? 'pointer' : 'default',
                }}
              >
                <span
                  aria-hidden
                  style={{
                    width: 24, height: 24, borderRadius: '50%', flexShrink: 0,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontFamily: MONO, fontSize: 11, lineHeight: 1,
                    background: done ? C.forest : active ? C.ink : 'transparent',
                    color: done || active ? C.white : C.inkSoft,
                    border: done || active ? 'none' : `1px solid ${C.lineStrong}`,
                  }}
                >
                  {done ? '✓' : i + 1}
                </span>
                <span style={{
                  fontFamily: SANS, fontSize: 14,
                  fontWeight: active ? 500 : 400,
                  color: active ? C.ink : C.inkSoft,
                  whiteSpace: 'nowrap',
                }}>
                  {step.label}
                </span>
              </button>
              {i < steps.length - 1 && (
                <span
                  aria-hidden
                  style={{
                    width: 40, height: 1, margin: '0 12px',
                    background: i < currentIndex ? C.forest : C.line,
                  }}
                />
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
