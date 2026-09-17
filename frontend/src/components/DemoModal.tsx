// "Request a demo" form.
//
// There is no endpoint behind this yet — the backend has no mail transport and
// no leads table. It shows the confirmation state so the flow can be reviewed,
// but nothing is sent anywhere, which is why the confirmation avoids promising
// that a message was delivered.

import { useState } from 'react'

import { C, MONO, RADIUS_CONTROL, SANS, serif } from '../design'
import { Field, Modal, ModalHeading, SolidBtn } from './primitives'

export default function DemoModal({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ name: '', dealership: '', email: '', phone: '', message: '' })
  const [submitted, setSubmitted] = useState(false)

  return (
    <Modal onClose={onClose} maxWidth={480}>
      <ModalHeading
        title="Request a demo"
        onClose={onClose}
        subtitle="We provision accounts directly. Tell us about your yard and we'll be in touch."
      />
      <div style={{ padding: 32 }}>
        {submitted ? (
          <div style={{ textAlign: 'center', padding: '16px 0 8px' }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" style={{ display: 'block', margin: '0 auto 16px' }}>
              <path d="M5 12L10 17L19 7" stroke={C.ink} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <p style={{ ...serif(28), color: C.ink, margin: '0 0 8px', letterSpacing: '-0.01em' }}>Request received.</p>
            <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0 }}>
              We'll be in touch within one business day.
            </p>
          </div>
        ) : (
          <form
            onSubmit={e => { e.preventDefault(); setSubmitted(true) }}
            style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
          >
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="Name" value={form.name} onChange={v => setForm(f => ({ ...f, name: v }))} placeholder="Alex Chen" />
              <Field label="Dealership" value={form.dealership} onChange={v => setForm(f => ({ ...f, dealership: v }))} placeholder="Pacific Motors" />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="Email" type="email" value={form.email} onChange={v => setForm(f => ({ ...f, email: v }))} placeholder="alex@pacificmotors.co.nz" />
              <Field label="Phone" type="tel" value={form.phone} onChange={v => setForm(f => ({ ...f, phone: v }))} placeholder="+61 4xx xxx xxx" />
            </div>
            <div>
              <label style={{
                fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
                display: 'block', marginBottom: 5, textTransform: 'uppercase',
              }}>
                What are you hoping to fix?
              </label>
              <textarea
                value={form.message}
                onChange={e => setForm(f => ({ ...f, message: e.target.value }))}
                placeholder="e.g. Our photos take too long to edit and quality is inconsistent."
                style={{
                  width: '100%', fontFamily: SANS, fontSize: 14, color: C.ink,
                  background: C.paper, borderRadius: RADIUS_CONTROL, padding: '10px 14px',
                  outline: 'none', boxSizing: 'border-box', resize: 'vertical', minHeight: 80,
                  border: `1px solid ${C.lineStrong}`, transition: 'border-color 0.15s',
                }}
                onFocus={e => (e.currentTarget.style.borderColor = C.forest)}
                onBlur={e => (e.currentTarget.style.borderColor = C.lineStrong)}
              />
            </div>
            <SolidBtn type="submit" full>Request a demo</SolidBtn>
          </form>
        )}
      </div>
    </Modal>
  )
}
