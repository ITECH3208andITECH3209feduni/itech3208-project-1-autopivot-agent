// Create a listing and attach its photographs.
//
// The Upload design shows only a drop zone and a URL field, but make, model and
// year are NOT NULL in the schema — a listing cannot be built from photographs
// alone, and the dashboard's "2021 Mazda CX-5 GT" has to come from somewhere.
// The vehicle details step is added for that reason.

import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { Card, Field, SolidBtn } from '../components/primitives'
import { C, MONO, RADIUS_CARD, RADIUS_CONTROL, SANS, serif } from '../design'
import { useIsMobile } from '../useMediaQuery'

const MAX_FILE_MB = 25
const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp']

type Draft = { file: File; previewUrl: string }

export default function UploadView() {
  const navigate = useNavigate()
  const mobile = useIsMobile()

  const [make, setMake] = useState('')
  const [model, setModel] = useState('')
  const [year, setYear] = useState('')
  const [variant, setVariant] = useState('')
  const [stockNumber, setStockNumber] = useState('')

  const [drafts, setDrafts] = useState<Draft[]>([])
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  // Listing URL import. Held separately from `error` so a site that refuses
  // the import does not read as a problem with the vehicle details.
  const [importUrl, setImportUrl] = useState('')
  const [importError, setImportError] = useState<string | null>(null)
  // Set when the vehicle saved but its URL import did not, so the page can
  // offer a way through to the listing that already exists.
  const [savedListingId, setSavedListingId] = useState<number | null>(null)

  function addFiles(incoming: FileList | File[]) {
    const rejected: string[] = []
    const accepted: Draft[] = []

    for (const file of Array.from(incoming)) {
      if (!ACCEPTED.includes(file.type)) {
        rejected.push(`${file.name} is not a JPEG, PNG or WEBP`)
      } else if (file.size > MAX_FILE_MB * 1024 * 1024) {
        rejected.push(`${file.name} is larger than ${MAX_FILE_MB} MB`)
      } else {
        accepted.push({ file, previewUrl: URL.createObjectURL(file) })
      }
    }

    setError(rejected.length ? rejected.join('. ') : null)
    setDrafts(current => [...current, ...accepted])
  }

  function removeDraft(index: number) {
    setDrafts(current => {
      URL.revokeObjectURL(current[index].previewUrl)
      return current.filter((_, i) => i !== index)
    })
  }

  const yearNumber = Number(year)
  const canSubmit =
    make.trim() !== '' &&
    model.trim() !== '' &&
    Number.isInteger(yearNumber) &&
    yearNumber >= 1886 &&
    yearNumber <= 2100 &&
    !busy

  async function handleSubmit() {
    setBusy(true)
    setError(null)
    setImportError(null)
    try {
      const listing = await api.createListing({
        make: make.trim(),
        model: model.trim(),
        year: yearNumber,
        variant: variant.trim() || null,
        stock_number: stockNumber.trim() || null,
      })

      if (drafts.length) {
        // The listing exists before its photographs do, so a failed upload
        // leaves a listing to add them to rather than losing the details.
        await api.uploadImages(listing.id, drafts.map(d => d.file))
      }

      if (importUrl.trim()) {
        // The import runs against the saved listing, so a site that refuses
        // costs the URL and nothing else. The listing and any uploaded
        // photographs are already safe.
        try {
          await api.importImagesFromUrl(listing.id, importUrl.trim())
        } catch (err) {
          drafts.forEach(d => URL.revokeObjectURL(d.previewUrl))
          setImportError((err as Error).message)
          setSavedListingId(listing.id)
          return
        }
      }

      drafts.forEach(d => URL.revokeObjectURL(d.previewUrl))
      navigate(`/app/vehicles/${listing.id}`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 32px', letterSpacing: '-0.02em', lineHeight: 1 }}>
        Upload
      </h1>

      {error && (
        <div role="alert" style={{
          fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
          borderRadius: 8, padding: '12px 16px', marginBottom: 24,
        }}>
          {error}
        </div>
      )}

      <Card style={{ padding: 24, marginBottom: 16 }}>
        <p style={{ fontFamily: SANS, fontSize: 18, fontWeight: 500, color: C.ink, margin: '0 0 4px' }}>
          Vehicle details
        </p>
        <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 20px' }}>
          Make, model and year identify the listing. Everything else is optional.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1fr' : 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
          <Field label="Make" value={make} onChange={setMake} placeholder="Mazda" disabled={busy} />
          <Field label="Model" value={model} onChange={setModel} placeholder="CX-5" disabled={busy} />
          <Field label="Year" value={year} onChange={setYear} placeholder="2021" disabled={busy} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1fr' : 'repeat(2, 1fr)', gap: 12 }}>
          <Field label="Variant" value={variant} onChange={setVariant} placeholder="GT (optional)" disabled={busy} />
          <Field label="Stock number" value={stockNumber} onChange={setStockNumber} placeholder="4471 (optional)" disabled={busy} />
        </div>
      </Card>

      <Card style={{ padding: 24, marginBottom: 16 }}>
        <p style={{ fontFamily: SANS, fontSize: 18, fontWeight: 500, color: C.ink, margin: '0 0 20px' }}>
          Photographs
        </p>

        <input
          ref={fileInput}
          type="file"
          multiple
          accept={ACCEPTED.join(',')}
          style={{ display: 'none' }}
          onChange={e => {
            if (e.target.files) addFiles(e.target.files)
            e.target.value = ''
          }}
        />

        <div
          onClick={() => fileInput.current?.click()}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => {
            e.preventDefault()
            setDragging(false)
            if (e.dataTransfer.files) addFiles(e.dataTransfer.files)
          }}
          style={{
            border: `1px dashed ${dragging ? C.forest : C.lineStrong}`,
            background: dragging ? C.forestTint : 'none',
            borderRadius: RADIUS_CONTROL, padding: '40px 24px', textAlign: 'center',
            cursor: 'pointer', transition: 'border-color 0.15s, background 0.15s',
          }}
        >
          <p style={{ fontFamily: SANS, fontSize: 15, color: C.ink, margin: '0 0 4px' }}>
            Drop vehicle photos here
          </p>
          <p style={{ fontFamily: SANS, fontSize: 14, color: C.forest, margin: '0 0 10px' }}>
            or browse files
          </p>
          <p style={{
            fontFamily: MONO, fontSize: 11, color: C.inkSoft, margin: 0,
            letterSpacing: '0.08em', textTransform: 'uppercase',
          }}>
            JPEG, PNG, WEBP — up to {MAX_FILE_MB} MB each
          </p>
        </div>

        {drafts.length > 0 && (
          <>
            <p style={{
              fontFamily: MONO, fontSize: 11, color: C.inkSoft, margin: '20px 0 10px',
              letterSpacing: '0.08em', textTransform: 'uppercase',
            }}>
              {drafts.length} photo{drafts.length === 1 ? '' : 's'} ready
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 10 }}>
              {drafts.map((draft, i) => (
                <div key={draft.previewUrl} style={{ position: 'relative' }}>
                  <img
                    src={draft.previewUrl}
                    alt={draft.file.name}
                    style={{
                      width: '100%', height: 84, objectFit: 'cover',
                      borderRadius: 8, display: 'block', background: C.line,
                    }}
                  />
                  <button
                    onClick={() => removeDraft(i)}
                    aria-label={`Remove ${draft.file.name}`}
                    disabled={busy}
                    style={{
                      position: 'absolute', top: 4, right: 4, width: 20, height: 20,
                      borderRadius: '50%', border: 'none', cursor: 'pointer',
                      background: 'rgba(26,26,23,0.72)', color: C.bone,
                      fontFamily: SANS, fontSize: 12, lineHeight: 1, padding: 0,
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      <Card style={{ padding: 24, marginBottom: 16 }}>
        <p style={{ fontFamily: SANS, fontSize: 18, fontWeight: 500, color: C.ink, margin: '0 0 4px' }}>
          Import from a listing URL
        </p>
        <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 16px', lineHeight: 1.6 }}>
          Optional. Paste a listing page and its photographs are fetched into
          this vehicle. <strong style={{ fontWeight: 500, color: C.ink }}>This does not
          work on every site</strong> — some block automated requests, and others
          build their gallery in the browser, leaving nothing in the page to
          read. When that happens you are told which, and the vehicle still saves.
        </p>

        <Field
          label="Listing URL"
          value={importUrl}
          onChange={setImportUrl}
          placeholder="https://… (optional)"
          disabled={busy}
        />

        {importError && (
          <div role="alert" style={{
            fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
            borderRadius: 8, padding: '12px 16px', marginTop: 16, lineHeight: 1.6,
          }}>
            {importError}
            {savedListingId !== null && (
              <>
                {' '}The vehicle was saved.{' '}
                <button
                  onClick={() => navigate(`/app/vehicles/${savedListingId}`)}
                  style={{
                    fontFamily: SANS, fontSize: 14, color: C.rust, background: 'none',
                    border: 'none', padding: 0, cursor: 'pointer',
                    textDecoration: 'underline', fontWeight: 500,
                  }}
                >
                  Open it and add photographs
                </button>.
              </>
            )}
          </div>
        )}
      </Card>

      <div style={{
        border: `1px dashed ${C.line}`, borderRadius: RADIUS_CARD,
        padding: '16px 20px', marginBottom: 24,
      }}>
        <p style={{
          fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
          textTransform: 'uppercase', margin: '0 0 6px',
        }}>
          Not wired yet
        </p>
        <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0, lineHeight: 1.6 }}>
          Backdrop selection happens on the vehicle page, not here. For now this
          saves the vehicle and its originals.
        </p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <SolidBtn onClick={handleSubmit} disabled={!canSubmit}>
          {busy ? 'Saving…' : 'Create listing'}
        </SolidBtn>
        {!canSubmit && !busy && (
          <span style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>
            Make, model and a year between 1886 and 2100 are required.
          </span>
        )}
      </div>
    </div>
  )
}
