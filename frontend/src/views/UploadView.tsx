// Step one of the workflow: get a vehicle, its photographs and its backdrop in,
// then hand straight over to processing.
//
// The Upload design shows only a drop zone and a URL field, but make, model and
// year are NOT NULL in the schema — a listing cannot be built from photographs
// alone, and the dashboard's "2021 Mazda CX-5 GT" has to come from somewhere.
// The vehicle details step is added for that reason.
//
// It used to end by dropping the dealer on the vehicle page to find "process"
// for themselves, and a note here said backdrop selection happened elsewhere.
// Both were the same fault: three screens that each did a third of one job. So
// the backdrop is chosen here, the last button starts the run, and the dealer
// lands on Processing already watching it. The vehicle page keeps its own
// controls for everything that comes back to a listing later.
//
// The order of operations is deliberate and hard-won. The listing is created
// before the photographs are uploaded, so a failed upload leaves a listing to
// retry into rather than losing the typed details; the URL import runs last,
// against the saved listing, because it is the step most likely to fail.

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type Backdrop } from '../api/client'
import AuthedImage from '../components/AuthedImage'
import { Card, Field, SolidBtn, Stepper, TextBtn, type Step } from '../components/primitives'
import { C, MONO, RADIUS_CONTROL, SANS, serif } from '../design'
import { WORKFLOW_STEPS, stepHref, type WorkflowStep } from '../workflow'

const MAX_FILE_MB = 25
const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp']
// A form does not improve with a metre of width. The shell centres the page at
// up to 1520px for galleries; this holds the reading and typing to something a
// person can scan on a 32-inch monitor, while the grids inside still reflow.
const FORM_MAX_WIDTH = 1080

type Draft = { file: File; previewUrl: string }

function Section({ step, title, description, children }: {
  step: string
  title: string
  description?: ReactNode
  children: ReactNode
}) {
  return (
    <Card style={{ padding: 24, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: description ? 6 : 20 }}>
        <span style={{
          fontFamily: MONO, fontSize: 11, color: C.inkSoft, letterSpacing: '0.08em',
        }}>
          {step}
        </span>
        <h2 style={{ fontFamily: SANS, fontSize: 18, fontWeight: 500, color: C.ink, margin: 0 }}>
          {title}
        </h2>
      </div>
      {description && (
        <p style={{
          fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 20px',
          lineHeight: 1.6, maxWidth: 640,
        }}>
          {description}
        </p>
      )}
      {children}
    </Card>
  )
}

/** Guidelines §9: thumbnail and label, forest border and tint when selected. */
function BackdropChoice({
  label, hint, selected, disabled, onSelect, preview,
}: {
  label: string
  hint: string
  selected: boolean
  disabled: boolean
  onSelect: () => void
  preview: ReactNode
}) {
  const [focused, setFocused] = useState(false)

  return (
    <label style={{
      display: 'block', borderRadius: RADIUS_CONTROL, overflow: 'hidden',
      border: `1px solid ${selected ? C.forest : C.lineStrong}`,
      background: selected ? C.forestTint : C.white,
      cursor: disabled ? 'not-allowed' : 'pointer',
      // The native ring lands on a 13px radio inside a large tile, which is
      // easy to lose. Repeating it around the tile is what makes keyboard
      // position obvious without suppressing the real focus indicator.
      outline: focused ? `2px solid ${C.forest}` : 'none',
      outlineOffset: 2,
      transition: 'border-color 0.15s, background 0.15s',
    }}>
      {preview}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '10px 12px' }}>
        <input
          type="radio"
          name="backdrop"
          checked={selected}
          disabled={disabled}
          onChange={onSelect}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          style={{ marginTop: 3, accentColor: C.forest, flexShrink: 0 }}
        />
        <span style={{ minWidth: 0 }}>
          <span style={{
            display: 'block', fontFamily: SANS, fontSize: 14, color: C.ink,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>
            {label}
          </span>
          <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, color: C.inkSoft }}>
            {hint}
          </span>
        </span>
      </div>
    </label>
  )
}

export default function UploadView() {
  const navigate = useNavigate()

  const [make, setMake] = useState('')
  const [model, setModel] = useState('')
  const [year, setYear] = useState('')
  const [variant, setVariant] = useState('')
  const [stockNumber, setStockNumber] = useState('')

  const [drafts, setDrafts] = useState<Draft[]>([])
  const [dragging, setDragging] = useState(false)
  // The label doubles as the busy flag: a four-stage submit should say which
  // stage it is on rather than leave "Saving…" up while it uploads 40 MB.
  const [busyLabel, setBusyLabel] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  // Listing URL import. Held separately from `error` so a site that refuses
  // the import does not read as a problem with the vehicle details.
  const [importUrl, setImportUrl] = useState('')
  const [importError, setImportError] = useState<string | null>(null)
  const [importNote, setImportNote] = useState<string | null>(null)

  // Set the moment the listing exists on the server. Everything after that
  // point is recoverable rather than lost, and a second press must not create
  // a second vehicle.
  const [savedListingId, setSavedListingId] = useState<number | null>(null)
  const [attachedCount, setAttachedCount] = useState(0)

  const [backdrops, setBackdrops] = useState<Backdrop[] | null>(null)
  const [backdropId, setBackdropId] = useState<number | null>(null)

  const busy = busyLabel !== null

  // Object URLs outlive the component unless they are revoked, and leaving the
  // page mid-form is the most likely way to leave some behind. The ref is what
  // lets the unmount cleanup see the current drafts without re-running.
  const draftsRef = useRef<Draft[]>([])
  draftsRef.current = drafts
  useEffect(() => () => {
    draftsRef.current.forEach(d => URL.revokeObjectURL(d.previewUrl))
  }, [])

  useEffect(() => {
    let cancelled = false
    api.backdrops()
      .then(next => {
        if (cancelled) return
        setBackdrops(next)
        // The dealership's default is the sensible starting choice; anything
        // else asks the dealer to make a decision they usually do not have.
        const preferred = next.find(b => b.is_default)
        if (preferred) setBackdropId(preferred.id)
      })
      .catch(() => {
        // The library is optional — a vehicle processes onto transparency
        // without one — so a failure here must not block the form.
        if (!cancelled) setBackdrops([])
      })
    return () => { cancelled = true }
  }, [])

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
  const detailsValid =
    make.trim() !== '' &&
    model.trim() !== '' &&
    Number.isInteger(yearNumber) &&
    yearNumber >= 1886 &&
    yearNumber <= 2100

  const willImport = importUrl.trim() !== ''
  const queuedHere = drafts.length > 0 || willImport
  const chosenBackdrop = backdrops?.find(b => b.id === backdropId) ?? null

  /** The last step, split out so the recovery panel can retry just this part. */
  async function startProcessing(listingId: number, attached: number) {
    if (attached === 0) {
      // Nothing to process. The vehicle is real, so go to it rather than to a
      // progress screen with nothing on it.
      navigate(`/app/vehicles/${listingId}`)
      return
    }
    setBusyLabel('Starting processing…')
    setError(null)
    try {
      await api.processListing(listingId, backdropId)
      navigate(`/app/processing/${listingId}`)
    } catch (err) {
      // The server says useful things here — that this deployment has no
      // vehicle processor, or that every photograph is already done — so its
      // words are shown rather than replaced with a generic failure.
      setError((err as Error).message)
      setBusyLabel(null)
    }
  }

  async function handleSubmit() {
    setError(null)
    setImportError(null)
    setImportNote(null)

    let listingId = savedListingId
    if (listingId === null) {
      setBusyLabel('Saving the vehicle…')
      try {
        const listing = await api.createListing({
          make: make.trim(),
          model: model.trim(),
          year: yearNumber,
          variant: variant.trim() || null,
          stock_number: stockNumber.trim() || null,
        })
        listingId = listing.id
        setSavedListingId(listing.id)
      } catch (err) {
        setError((err as Error).message)
        setBusyLabel(null)
        return
      }
    }

    let attached = attachedCount

    if (drafts.length) {
      setBusyLabel(`Uploading ${drafts.length} photograph${drafts.length === 1 ? '' : 's'}…`)
      try {
        await api.uploadImages(listingId, drafts.map(d => d.file))
        attached += drafts.length
        // Uploaded files are on the server now, so the local previews are both
        // redundant and a leak waiting to happen.
        drafts.forEach(d => URL.revokeObjectURL(d.previewUrl))
        setDrafts([])
        setAttachedCount(attached)
      } catch (err) {
        setError((err as Error).message)
        setBusyLabel(null)
        return
      }
    }

    if (importUrl.trim()) {
      setBusyLabel('Fetching photographs from the listing…')
      try {
        const result = await api.importImagesFromUrl(listingId, importUrl.trim())
        attached += result.images.length
        setAttachedCount(attached)
        setImportNote(result.note)
        // Cleared so a retry of anything later does not import the same
        // gallery twice.
        setImportUrl('')
      } catch (err) {
        // The vehicle and any uploaded photographs are already safe: a site
        // that refuses costs the URL and nothing else. Stop here so the dealer
        // decides what to do rather than being carried past the failure.
        setImportError((err as Error).message)
        setBusyLabel(null)
        return
      }
    }

    await startProcessing(listingId, attached)
  }

  function goToStep(step: Step) {
    // The Stepper leaves the current step clickable so it can be announced as
    // a button; navigating to the page you are already on would only add a
    // history entry to back out of.
    if (step.key === 'upload') return
    const href = stepHref(step.key as WorkflowStep, savedListingId)
    if (href) navigate(href)
  }

  // The button says which of the four things it is about to do, and the
  // sentence beside it says what that means, because "Create listing" told a
  // dealer nothing about whether their photographs were about to be processed.
  const backdropPhrase = chosenBackdrop ? `onto ${chosenBackdrop.name}` : 'onto transparency'
  const queuedPhrase = drafts.length > 0
    ? `${drafts.length} photograph${drafts.length === 1 ? '' : 's'}${willImport ? ' and whatever the listing URL gives up' : ''}`
    : 'whatever the listing URL gives up'

  const primaryLabel = busyLabel ?? (
    savedListingId !== null
      ? queuedHere ? 'Add these and start processing'
        : 'Start processing'
      : queuedHere ? 'Save and start processing'
        : 'Save vehicle'
  )

  const plan = savedListingId !== null
    ? queuedHere
      ? `Uploads ${queuedPhrase} to the vehicle that is already saved, then starts processing ${backdropPhrase}.`
      : `Starts processing the ${attachedCount} photograph${attachedCount === 1 ? '' : 's'} already on this vehicle, ${backdropPhrase}.`
    : queuedHere
      ? `Saves the vehicle, uploads ${queuedPhrase}, then starts processing ${backdropPhrase}.`
      : 'Saves the vehicle so you can add photographs to it later. Nothing is processed until there are some.'

  return (
    <div style={{ maxWidth: FORM_MAX_WIDTH }}>
      <Stepper steps={WORKFLOW_STEPS} current="upload" onNavigate={goToStep} />

      <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 8px', letterSpacing: '-0.02em', lineHeight: 1 }}>
        Add a vehicle
      </h1>
      <p style={{
        fontFamily: SANS, fontSize: 15, color: C.inkSoft, margin: '0 0 32px',
        lineHeight: 1.6, maxWidth: 640,
      }}>
        Details, photographs, then the backdrop they are placed onto. The last
        button here starts the run and takes you to it.
      </p>

      {error && (
        <div role="alert" style={{
          fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
          borderRadius: 8, padding: '12px 16px', marginBottom: 24, lineHeight: 1.6,
        }}>
          {error}
        </div>
      )}

      <Section
        step="01"
        title="Vehicle details"
        description="Make, model and year identify the listing. Everything else is optional."
      >
        {/* auto-fit rather than a column count: three fields side by side on a
            wide monitor, stacked on a laptop, without either being named. */}
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 12, marginBottom: 12,
        }}>
          <Field label="Make" value={make} onChange={setMake} placeholder="Mazda" disabled={busy} />
          <Field label="Model" value={model} onChange={setModel} placeholder="CX-5" disabled={busy} />
          <Field label="Year" value={year} onChange={setYear} placeholder="2021" disabled={busy} />
        </div>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12,
        }}>
          <Field label="Variant" value={variant} onChange={setVariant} placeholder="GT (optional)" disabled={busy} />
          <Field label="Stock number" value={stockNumber} onChange={setStockNumber} placeholder="4471 (optional)" disabled={busy} />
        </div>
      </Section>

      <Section
        step="02"
        title="Photographs"
        description="The originals the pipeline works from. They stay on the listing untouched — processing writes new images beside them."
      >
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

        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          disabled={busy}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => {
            e.preventDefault()
            setDragging(false)
            if (e.dataTransfer.files) addFiles(e.dataTransfer.files)
          }}
          style={{
            display: 'block', width: '100%',
            border: `1px dashed ${dragging ? C.forest : C.lineStrong}`,
            background: dragging ? C.forestTint : 'none',
            borderRadius: RADIUS_CONTROL, padding: '40px 24px', textAlign: 'center',
            cursor: busy ? 'not-allowed' : 'pointer', transition: 'border-color 0.15s, background 0.15s',
          }}
        >
          <span style={{ display: 'block', fontFamily: SANS, fontSize: 15, color: C.ink, marginBottom: 4 }}>
            Drop vehicle photos here
          </span>
          <span style={{ display: 'block', fontFamily: SANS, fontSize: 14, color: C.forest, marginBottom: 10 }}>
            or browse files
          </span>
          <span style={{
            display: 'block', fontFamily: MONO, fontSize: 11, color: C.inkSoft,
            letterSpacing: '0.08em', textTransform: 'uppercase',
          }}>
            JPEG, PNG, WEBP — up to {MAX_FILE_MB} MB each
          </span>
        </button>

        {attachedCount > 0 && (
          <p style={{
            fontFamily: SANS, fontSize: 14, color: C.forest, margin: '16px 0 0', lineHeight: 1.6,
          }}>
            {attachedCount} photograph{attachedCount === 1 ? '' : 's'} already uploaded to this
            vehicle. Anything you add now is uploaded alongside them.
          </p>
        )}

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
                  {/* A local file, not a stored one: this is the one place a
                      plain <img> is correct, because there is no request to
                      authenticate. */}
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

        <div style={{ borderTop: `1px solid ${C.line}`, margin: '24px 0 20px' }} />

        <h3 style={{ fontFamily: SANS, fontSize: 15, fontWeight: 500, color: C.ink, margin: '0 0 6px' }}>
          Or import from a listing URL
        </h3>
        <p style={{
          fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 16px',
          lineHeight: 1.6, maxWidth: 640,
        }}>
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

        {importNote && (
          <p style={{
            fontFamily: SANS, fontSize: 14, color: C.amberText, background: C.amberTint,
            borderRadius: 8, padding: '12px 16px', margin: '16px 0 0', lineHeight: 1.6,
          }}>
            {importNote}
          </p>
        )}

        {importError && (
          <div role="alert" style={{
            fontFamily: SANS, fontSize: 14, color: C.rust, background: C.rustTint,
            borderRadius: 8, padding: '12px 16px', marginTop: 16, lineHeight: 1.6,
          }}>
            {importError} The vehicle was saved, and so was anything you uploaded
            — pick up from below.
          </div>
        )}
      </Section>

      <Section
        step="03"
        title="Backdrop"
        description="The scene each vehicle is placed onto once it has been cut out and its plates covered. One choice covers the whole run."
      >
        {backdrops === null ? (
          <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0 }}>
            Loading your backdrops…
          </p>
        ) : (
          <>
            <div
              role="radiogroup"
              aria-label="Backdrop"
              style={{
                display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12,
              }}
            >
              <BackdropChoice
                label="No backdrop"
                hint="transparent"
                selected={backdropId === null}
                disabled={busy}
                onSelect={() => setBackdropId(null)}
                preview={
                  <div
                    aria-hidden
                    style={{
                      width: '100%', aspectRatio: '4 / 3',
                      // The chequerboard that means transparency everywhere else
                      // in image software, drawn from the palette rather than an
                      // asset.
                      background: `repeating-conic-gradient(${C.bone} 0% 25%, ${C.white} 0% 50%) 50% / 18px 18px`,
                    }}
                  />
                }
              />

              {backdrops.map(backdrop => (
                <BackdropChoice
                  key={backdrop.id}
                  label={backdrop.name}
                  hint={backdrop.suits_angles.length ? backdrop.suits_angles.join(', ').replace(/_/g, ' ') : 'all angles'}
                  selected={backdropId === backdrop.id}
                  disabled={busy}
                  onSelect={() => setBackdropId(backdrop.id)}
                  preview={
                    <AuthedImage
                      src={backdrop.image_url}
                      alt={`Backdrop — ${backdrop.name}`}
                      style={{ width: '100%', aspectRatio: '4 / 3', display: 'block' }}
                    />
                  }
                />
              ))}
            </div>

            {backdrops.length === 0 && (
              <p style={{
                fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '16px 0 0',
                lineHeight: 1.6, maxWidth: 640,
              }}>
                Your backdrop library is empty, so vehicles come back cut out on
                transparency — usable, but not a finished listing photograph. Add
                the scenes your dealership shoots against under Backdrops in the
                sidebar, then come back.
              </p>
            )}
          </>
        )}
      </Section>

      {savedListingId === null ? (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginTop: 24,
        }}>
          <SolidBtn onClick={handleSubmit} disabled={!detailsValid || busy}>
            {primaryLabel}
          </SolidBtn>
          <span style={{
            fontFamily: SANS, fontSize: 14, color: C.inkSoft, lineHeight: 1.6, maxWidth: 520,
          }}>
            {detailsValid ? plan : 'Make, model and a year between 1886 and 2100 are required.'}
          </span>
        </div>
      ) : (
        // Once the listing exists, this panel is the only action area on the
        // screen. Two solid buttons offering the same run would be one more
        // decision than the situation deserves, and the guidelines allow one
        // primary action per view.
        <Card style={{ padding: 24, marginTop: 24, borderColor: C.lineStrong }}>
          <h2 style={{ fontFamily: SANS, fontSize: 18, fontWeight: 500, color: C.ink, margin: '0 0 6px' }}>
            This vehicle is saved
          </h2>
          <p style={{
            fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: '0 0 16px',
            lineHeight: 1.6, maxWidth: 640,
          }}>
            {attachedCount > 0
              ? `${attachedCount} photograph${attachedCount === 1 ? ' is' : 's are'} attached to it, and nothing above needs typing again. `
              : 'Nothing has been attached to it yet, and nothing above needs typing again. '}
            {attachedCount > 0 || queuedHere
              ? plan
              : 'Add photographs above, or open the vehicle and add them there.'}
          </p>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            {(attachedCount > 0 || queuedHere) && (
              <SolidBtn onClick={handleSubmit} disabled={busy}>
                {primaryLabel}
              </SolidBtn>
            )}
            <TextBtn onClick={() => navigate(`/app/vehicles/${savedListingId}`)}>
              Open it and add photographs
            </TextBtn>
          </div>
        </Card>
      )}
    </div>
  )
}
