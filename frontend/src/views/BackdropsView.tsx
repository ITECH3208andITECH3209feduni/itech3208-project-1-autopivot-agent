// The dealership's backdrop library, read from and written to the API.
//
// The Figma Make version showed five hardcoded Unsplash backdrops with invented
// "suits" metadata. A new dealership genuinely starts with none.

import { useEffect, useRef, useState } from 'react'

import { api, type Backdrop } from '../api/client'
import AuthedImage from '../components/AuthedImage'
import { Card, SolidBtn } from '../components/primitives'
import { C, MONO, RADIUS_CARD, SANS, serif } from '../design'

function describeAngles(angles: string[]): string {
  if (angles.length === 0) return 'suits: all angles'
  return `suits: ${angles.join(', ').replace(/_/g, ' ')}`
}

export default function BackdropsView() {
  const [backdrops, setBackdrops] = useState<Backdrop[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

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

  async function handleDelete(backdrop: Backdrop) {
    setError(null)
    try {
      await api.deleteBackdrop(backdrop.id)
      await load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 32 }}>
        <h1 style={{ ...serif(40), color: C.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1 }}>
          Backdrops
        </h1>
        <SolidBtn onClick={() => fileInput.current?.click()} disabled={uploading}>
          {uploading ? 'Uploading…' : 'Upload backdrop'}
        </SolidBtn>
      </div>

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
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 16 }}>
          {backdrops.map(backdrop => (
            <Card key={backdrop.id} style={{ overflow: 'hidden' }}>
              <AuthedImage
                src={backdrop.image_url}
                alt={backdrop.name}
                style={{ width: '100%', height: 160, display: 'block' }}
              />
              <div style={{ padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
                  <p style={{ fontFamily: SANS, fontSize: 16, fontWeight: 500, color: C.ink, margin: '0 0 4px' }}>
                    {backdrop.name}
                  </p>
                  <button
                    onClick={() => void handleDelete(backdrop)}
                    style={{
                      fontFamily: SANS, fontSize: 13, color: C.inkSoft, background: 'none',
                      border: 'none', cursor: 'pointer', padding: 0,
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = C.rust)}
                    onMouseLeave={e => (e.currentTarget.style.color = C.inkSoft)}
                  >
                    Remove
                  </button>
                </div>
                <p style={{ fontFamily: MONO, fontSize: 11, color: C.inkSoft, margin: 0 }}>
                  {describeAngles(backdrop.suits_angles)}
                </p>
              </div>
            </Card>
          ))}

          <button
            onClick={() => fileInput.current?.click()}
            disabled={uploading}
            style={{
              minHeight: 232, border: `1px dashed ${C.lineStrong}`, borderRadius: RADIUS_CARD,
              background: 'none', cursor: uploading ? 'not-allowed' : 'pointer',
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              justifyContent: 'center', gap: 12,
            }}
          >
            <span style={{
              width: 32, height: 32, borderRadius: '50%', border: `1px solid ${C.lineStrong}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: SANS, fontSize: 18, color: C.inkSoft, lineHeight: 1,
            }}>
              +
            </span>
            <span style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>
              {backdrops.length === 0 ? 'Upload your first backdrop' : 'Upload your own'}
            </span>
          </button>
        </div>
      )}

      {backdrops !== null && backdrops.length === 0 && (
        <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, marginTop: 24, maxWidth: 520, lineHeight: 1.6 }}>
          Backdrops are the scenes your vehicles are placed into. Upload the ones
          your dealership shoots against — they belong to you alone and can be
          renamed or removed at any time.
        </p>
      )}
    </div>
  )
}
