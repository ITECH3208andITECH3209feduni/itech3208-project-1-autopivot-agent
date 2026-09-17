// The dealership's backdrop library, read from and written to the API.
//
// The Figma Make version showed five hardcoded Unsplash backdrops with invented
// "suits" metadata. A new dealership genuinely starts with none.
//
// Two things changed in this pass. A backdrop is a full scene — a forecourt, a
// studio sweep, a stretch of coast road — and nobody can judge one from a
// 160px strip, so a card opens into a full-size preview. And removing one used
// to happen on a single click of a quiet grey link, with no confirmation and
// nothing to undo it; it now goes through the shared confirmation dialog, which
// is also where the dealer is told that a backdrop already used to process
// images cannot be removed at all.

import { useEffect, useRef, useState } from 'react'

import { api, type Backdrop } from '../api/client'
import AuthedImage from '../components/AuthedImage'
import LibraryModal, { useDialogKeys } from '../components/LibraryModal'
import { Card, ConfirmDialog, ModalHeading, SolidBtn } from '../components/primitives'
import { C, CARD_SHADOW, MONO, RADIUS_CARD, SANS, serif } from '../design'
import { useIsCompact } from '../useMediaQuery'

// design.ts has one card shadow and no hover elevation, so this is that same
// two-layer ink shadow a step deeper — the figure the vehicle gallery on the
// dashboard lifts by, so the two libraries behave identically under the hand.
const RAISED_SHADOW = '0 2px 6px rgba(26,26,23,0.08), 0 10px 24px rgba(26,26,23,0.07)'

function describeAngles(angles: string[]): string {
  if (angles.length === 0) return 'suits: all angles'
  return `suits: ${angles.join(', ').replace(/_/g, ' ')}`
}

/** Day-month-year: the product is for Australian and New Zealand dealerships. */
function addedOn(iso: string): string {
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

function BackdropCard({
  backdrop, onPreview, onRemove,
}: {
  backdrop: Backdrop
  onPreview: () => void
  onRemove: () => void
}) {
  const [raised, setRaised] = useState(false)

  return (
    <li
      onClick={onPreview}
      onMouseEnter={() => setRaised(true)}
      onMouseLeave={() => setRaised(false)}
      // Focus bubbles, so reaching the card by keyboard lights it up exactly as
      // hovering it does.
      onFocus={() => setRaised(true)}
      onBlur={() => setRaised(false)}
      style={{
        background: C.white, borderRadius: RADIUS_CARD, overflow: 'hidden',
        border: `1px solid ${raised ? C.lineStrong : C.line}`,
        boxShadow: raised ? RAISED_SHADOW : CARD_SHADOW,
        cursor: 'pointer', display: 'flex', flexDirection: 'column',
      }}
    >
      <div style={{ position: 'relative', width: '100%', aspectRatio: '3 / 2', background: C.bone, overflow: 'hidden' }}>
        <AuthedImage
          src={backdrop.image_url}
          alt={backdrop.name}
          style={{ width: '100%', height: '100%', display: 'block' }}
        />
        {/* Solid ink rather than a translucent veil: it sits over a scene of
            unknown brightness, and only a solid ground guarantees the label
            keeps its contrast. Decorative — the button below carries the name
            of the action. */}
        <span
          aria-hidden
          style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', background: 'rgba(26,26,23,0.7)',
            opacity: raised ? 1 : 0, transition: 'opacity 0.18s', pointerEvents: 'none',
            fontFamily: MONO, fontSize: 10, letterSpacing: '0.1em',
            textTransform: 'uppercase', color: C.bone,
          }}
        >
          View full size
        </span>
      </div>

      <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
          {/* The card is a click target for a mouse; this button is what a
              keyboard reaches, and it names both the backdrop and the action.
              One tab stop for the preview, one for the removal, per card. */}
          <button
            onClick={event => { event.stopPropagation(); onPreview() }}
            aria-label={`Preview ${backdrop.name} full size`}
            style={{
              fontFamily: SANS, fontSize: 15, fontWeight: 500, color: raised ? C.forest : C.ink,
              background: 'none', border: 'none', padding: 0, cursor: 'pointer',
              textAlign: 'left', minWidth: 0, overflow: 'hidden', display: 'block',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap', transition: 'color 0.15s',
            }}
          >
            {backdrop.name}
          </button>

          <button
            onClick={event => { event.stopPropagation(); onRemove() }}
            aria-label={`Remove ${backdrop.name}`}
            style={{
              fontFamily: SANS, fontSize: 13, color: C.inkSoft, background: 'none',
              border: 'none', cursor: 'pointer', padding: 0, flexShrink: 0,
            }}
            onMouseEnter={event => (event.currentTarget.style.color = C.rust)}
            onMouseLeave={event => (event.currentTarget.style.color = C.inkSoft)}
          >
            Remove
          </button>
        </div>

        <p style={{ fontFamily: MONO, fontSize: 11, color: C.inkSoft, margin: 0 }}>
          {describeAngles(backdrop.suits_angles)}
        </p>
      </div>
    </li>
  )
}

/** The dashed tile that opens the file picker, in the grid and when empty. */
function UploadTile({
  label, disabled, onClick, minHeight,
}: {
  label: string
  disabled: boolean
  onClick: () => void
  minHeight: number
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        width: '100%', minHeight, border: `1px dashed ${C.lineStrong}`,
        borderRadius: RADIUS_CARD, background: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer', display: 'flex',
        flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12,
      }}
    >
      <span aria-hidden style={{
        width: 32, height: 32, borderRadius: '50%', border: `1px solid ${C.lineStrong}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: SANS, fontSize: 18, color: C.inkSoft, lineHeight: 1,
      }}>
        +
      </span>
      <span style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>{label}</span>
    </button>
  )
}

/** A backdrop at the size it is actually used: the whole frame. */
function BackdropPreview({
  backdrop, onClose, onRemove,
}: {
  backdrop: Backdrop
  onClose: () => void
  onRemove: () => void
}) {
  const compact = useIsCompact()

  return (
    <LibraryModal onClose={onClose} label={`Backdrop — ${backdrop.name}`} maxWidth={960}>
      <ModalHeading
        title={backdrop.name}
        subtitle={`${describeAngles(backdrop.suits_angles)} · added ${addedOn(backdrop.created_at)}`}
        onClose={onClose}
      />

      <div style={{ padding: compact ? '20px 20px 24px' : '24px 32px 32px' }}>
        <div style={{
          position: 'relative', height: compact ? 'min(42vh, 300px)' : 'min(52vh, 460px)',
          background: C.ink, borderRadius: 8, overflow: 'hidden',
        }}>
          <p style={{
            position: 'absolute', inset: 0, margin: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center', fontFamily: MONO,
            fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase',
            color: 'rgba(245,242,236,0.45)',
          }}>
            Loading backdrop
          </p>
          {/* contain, not cover: the point of the full-size view is to see the
              whole scene, including whatever headroom a vehicle gets composited
              into. AuthedImage's grey placeholder is overridden away so it does
              not flash against the ink ground. */}
          <AuthedImage
            src={backdrop.image_url}
            alt={`${backdrop.name}, full size`}
            style={{
              position: 'absolute', inset: 0, width: '100%', height: '100%',
              objectFit: 'contain', background: 'transparent',
            }}
          />
        </div>

        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 16, flexWrap: 'wrap', marginTop: 24,
        }}>
          <button
            onClick={onRemove}
            style={{
              fontFamily: SANS, fontSize: 14, color: C.rust, background: 'none',
              border: 'none', cursor: 'pointer', padding: '10px 0',
            }}
          >
            Remove this backdrop
          </button>
          <SolidBtn onClick={onClose}>Done</SolidBtn>
        </div>
      </div>
    </LibraryModal>
  )
}

export default function BackdropsView() {
  const [backdrops, setBackdrops] = useState<Backdrop[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [previewing, setPreviewing] = useState<Backdrop | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Backdrop | null>(null)
  const [deleting, setDeleting] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  // ConfirmDialog renders the Modal primitive itself and hands back no element,
  // so it cannot be given a focus trap from out here — but Escape and returning
  // focus to the Remove button that opened it are most of the gap, and both are
  // free. The guard on `deleting` matches the dialog's own behaviour: a
  // deletion in flight cannot be dismissed.
  useDialogKeys({
    active: pendingDelete !== null,
    onClose: () => { if (!deleting) setPendingDelete(null) },
  })

  async function load() {
    try {
      setBackdrops(await api.backdrops())
    } catch (err) {
      setError((err as Error).message)
    }
  }

  useEffect(() => { void load() }, [])

  async function handleFile(file: File) {
    // Name defaults to the filename without its extension; the library is keyed
    // on name per dealership, so a clash surfaces as a 409 from the server.
    const name = file.name.replace(/\.[^.]+$/, '').slice(0, 120) || 'Untitled'
    setUploading(true)
    setError(null)
    try {
      await api.createBackdrop(name, file)
      await load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return
    setDeleting(true)
    setError(null)
    try {
      await api.deleteBackdrop(pendingDelete.id)
      setPendingDelete(null)
      await load()
    } catch (err) {
      // A backdrop that has processed images against it comes back as a 409
      // with an explanation; the dialog closes so the message is not hidden
      // behind it.
      setError((err as Error).message)
      setPendingDelete(null)
    } finally {
      setDeleting(false)
    }
  }

  const isEmpty = backdrops !== null && backdrops.length === 0

  return (
    <div>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 16, flexWrap: 'wrap', marginBottom: 8,
      }}>
        <h1 style={{ ...serif(40), color: C.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1 }}>
          Backdrops
        </h1>
        <SolidBtn onClick={() => fileInput.current?.click()} disabled={uploading}>
          {uploading ? 'Uploading…' : 'Upload backdrop'}
        </SolidBtn>
      </div>

      <p style={{
        fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
        textTransform: 'uppercase', margin: '0 0 32px',
      }}>
        {backdrops === null
          ? 'Loading'
          : `${backdrops.length} in your library`}
      </p>

      <input
        ref={fileInput}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        style={{ display: 'none' }}
        onChange={e => {
          const file = e.target.files?.[0]
          if (file) void handleFile(file)
        }}
      />

      {error && (
        <div role="alert" style={{
          fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
          borderRadius: 8, padding: '12px 16px', marginBottom: 24,
        }}>
          {error}
        </div>
      )}

      {backdrops === null ? (
        <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>Loading…</p>
      ) : isEmpty ? (
        <Card style={{ padding: '56px 24px', textAlign: 'center' }}>
          <p style={{ fontFamily: SANS, fontSize: 16, color: C.ink, margin: '0 0 8px' }}>
            Your library is empty
          </p>
          <p style={{
            fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 auto 24px',
            maxWidth: 460, lineHeight: 1.6,
          }}>
            Backdrops are the scenes your vehicles are placed into. Upload the
            ones your dealership shoots against — a forecourt, a studio sweep,
            a stretch of road you like. They belong to you alone, nothing is
            shipped by default, and any of them can be removed while it is
            unused.
          </p>
          <div style={{ maxWidth: 320, margin: '0 auto' }}>
            <UploadTile
              label="Upload your first backdrop"
              disabled={uploading}
              minHeight={140}
              onClick={() => fileInput.current?.click()}
            />
          </div>
        </Card>
      ) : (
        // auto-fill, not a column count: the same markup gives five tracks on a
        // 32-inch monitor and three on a laptop without either number being
        // written down.
        <ul style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
          gap: 20, listStyle: 'none', margin: 0, padding: 0,
        }}>
          {backdrops.map(backdrop => (
            <BackdropCard
              key={backdrop.id}
              backdrop={backdrop}
              onPreview={() => setPreviewing(backdrop)}
              onRemove={() => setPendingDelete(backdrop)}
            />
          ))}
          <li style={{ display: 'flex' }}>
            <UploadTile
              label="Upload your own"
              disabled={uploading}
              minHeight={240}
              onClick={() => fileInput.current?.click()}
            />
          </li>
        </ul>
      )}

      {previewing && (
        <BackdropPreview
          backdrop={previewing}
          onClose={() => setPreviewing(null)}
          onRemove={() => {
            // One dialog at a time: the confirmation replaces the preview
            // rather than stacking on top of it, so Escape and the tab ring
            // always belong to a single thing.
            setPendingDelete(previewing)
            setPreviewing(null)
          }}
        />
      )}

      {pendingDelete && (
        <ConfirmDialog
          title={`Remove ${pendingDelete.name}?`}
          body={
            <>
              This backdrop is removed from your library and its file is deleted.
              Images already processed against it keep the backdrop they were
              given — and if it has been used, the server will refuse the removal
              so the record of how those images were made stays intact.
            </>
          }
          confirmLabel="Remove backdrop"
          busy={deleting}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  )
}
