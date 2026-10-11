
import { useEffect, useRef, useState } from 'react'

import { api, type Backdrop } from '../api/client'
import AuthedImage from '../components/AuthedImage'
import LibraryModal, { useDialogKeys } from '../components/LibraryModal'
import { Card, ConfirmDialog, ModalHeading, SolidBtn } from '../components/primitives'
import { C, CARD_SHADOW, MONO, RADIUS_CARD, SANS, serif } from '../design'
import { useIsCompact } from '../useMediaQuery'

const RAISED_SHADOW = '0 2px 6px rgba(26,26,23,0.08), 0 10px 24px rgba(26,26,23,0.07)'

const SHOT_ANGLES: { key: string; label: string }[] = [
  { key: 'front', label: 'Front' },
  { key: 'front_quarter', label: 'Front ¾' },
  { key: 'side', label: 'Side' },
  { key: 'rear_quarter', label: 'Rear ¾' },
  { key: 'rear', label: 'Rear' },
]

function AngleChips({ backdrop, onChange }: {
  backdrop: Backdrop
  onChange: (updated: Backdrop) => void
}) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function toggle(key: string) {
    const current = new Set(backdrop.suits_angles)
    if (current.has(key)) current.delete(key)
    else current.add(key)
    setSaving(true)
    setError(null)
    try {
      onChange(await api.setBackdropAngles(backdrop.id, [...current]))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div onClick={event => event.stopPropagation()}>
      <div role="group" aria-label={`Shot angles for ${backdrop.name}`}
        style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {SHOT_ANGLES.map(({ key, label }) => {
          const on = backdrop.suits_angles.includes(key)
          return (
            <button
              key={key}
              type="button"
              aria-pressed={on}
              disabled={saving}
              onClick={() => void toggle(key)}
              style={{
                fontFamily: SANS, fontSize: 12, borderRadius: 999, padding: '3px 10px',
                cursor: saving ? 'default' : 'pointer',
                border: `1px solid ${on ? C.forest : C.lineStrong}`,
                background: on ? C.forestTint : 'transparent',
                color: on ? C.forest : C.inkSoft,
              }}
            >
              {label}
            </button>
          )
        })}
      </div>
      {error && (
        <p role="alert" style={{ fontFamily: SANS, fontSize: 12, color: C.rust, margin: '6px 0 0' }}>
          {error}
        </p>
      )}
    </div>
  )
}

function describeAngles(angles: string[]): string {
  if (angles.length === 0) return 'suits: all angles'
  return `suits: ${angles.join(', ').replace(/_/g, ' ')}`
}

function addedOn(iso: string): string {
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

function BackdropCard({
  backdrop, onPreview, onRemove, onChange,
}: {
  backdrop: Backdrop
  onPreview: () => void
  onRemove: () => void
  onChange: (updated: Backdrop) => void
}) {
  const [raised, setRaised] = useState(false)

  return (
    <li
      onClick={onPreview}
      onMouseEnter={() => setRaised(true)}
      onMouseLeave={() => setRaised(false)}
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
        <AngleChips backdrop={backdrop} onChange={onChange} />
      </div>
    </li>
  )
}

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
              onChange={updated => setBackdrops(current =>
                current?.map(b => (b.id === updated.id ? updated : b)) ?? current)}
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
