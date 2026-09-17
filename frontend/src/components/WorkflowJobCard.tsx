// One photograph on its way through the pipeline.
//
// Processing used to draw a job as a row that said "Complete" and nothing
// else, which told a dealer neither which photograph it was about nor what
// came out of it. A card carries the thumbnail — the only thing that actually
// identifies a photograph to the person who took it — next to the outcome.
//
// The five states here are deliberately not the four the shared StatusPill
// knows. A job can fail, which a listing's processing_status never does; and a
// job can come back `completed` with review_state 'needs_review', meaning the
// pipeline ran perfectly and decided a person should look — no vehicle was
// found, or the photograph turned out to be an advertisement banner rather
// than a car. Calling that a failure would send a dealer hunting for a bug
// that is not there, so it gets its own words, its own icon and its own weight
// of colour.

import type { CSSProperties } from 'react'

import type { ListingImage, ProcessingJob } from '../api/client'
import { C, MONO, SANS } from '../design'
import AuthedImage from './AuthedImage'
import { Card } from './primitives'

export type WorkflowJobState = 'queued' | 'working' | 'ready' | 'needs_person' | 'failed'

/** The job's own fields, read the way a dealer would read them. */
export function workflowJobState(job: ProcessingJob): WorkflowJobState {
  if (job.status === 'failed') return 'failed'
  if (job.status === 'completed') {
    return job.review_state === 'needs_review' ? 'needs_person' : 'ready'
  }
  if (job.status === 'processing') return 'working'
  return 'queued'
}

export const WORKFLOW_STATE_LABEL: Record<WorkflowJobState, string> = {
  queued: 'Queued',
  working: 'Working',
  ready: 'Ready',
  needs_person: 'Needs a person',
  failed: 'Failed',
}

const BADGE_STYLE: Record<WorkflowJobState, CSSProperties> = {
  queued: { color: C.inkSoft, background: C.bone },
  // The same amber pairing the StatusPill uses for "Processing": amberText
  // rather than amber, because this is body-sized text on a tint.
  working: { color: C.amberText, background: C.amberTint },
  ready: { color: C.forest, background: C.forestTint },
  needs_person: { color: C.rust, background: C.rustTint },
  // Solid, not tinted. Guidelines §2 give rust to errors and to the
  // needs-review pill alike, so hue alone cannot separate a photograph the
  // pipeline set aside from one that broke. Weight does — and the label and
  // icon say it outright for anyone who cannot see either.
  failed: { color: C.white, background: C.rust },
}

/** The colour a card's own border takes, so a failure is findable in a grid. */
export function workflowJobAccent(state: WorkflowJobState): string {
  if (state === 'failed') return C.rust
  if (state === 'needs_person') return C.lineStrong
  return C.line
}

function StateIcon({ state }: { state: WorkflowJobState }) {
  const shared = {
    width: 12, height: 12, viewBox: '0 0 12 12', fill: 'none',
    style: { flexShrink: 0 }, 'aria-hidden': true,
  } as const

  if (state === 'ready') {
    return (
      <svg {...shared}>
        <path d="M2.5 6.3l2.3 2.3 4.7-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  if (state === 'failed') {
    return (
      <svg {...shared}>
        <path d="M6 2.6v3.9M6 8.4v.9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    )
  }
  if (state === 'needs_person') {
    // An eye: this photograph is waiting to be looked at, not repaired.
    return (
      <svg {...shared}>
        <path d="M1 6s1.9-3.1 5-3.1S11 6 11 6s-1.9 3.1-5 3.1S1 6 1 6z" stroke="currentColor" strokeWidth="1.2" />
        <circle cx="6" cy="6" r="1.3" fill="currentColor" />
      </svg>
    )
  }
  if (state === 'working') {
    return (
      <svg {...shared}>
        <circle cx="6" cy="6" r="4.2" stroke="currentColor" strokeWidth="1.2" opacity="0.45" />
        <path d="M6 1.8A4.2 4.2 0 0110.2 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    )
  }
  return (
    <svg {...shared}>
      <circle cx="6" cy="6" r="4.2" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  )
}

/** The pill shape of the design system, carrying a job's vocabulary. */
export function WorkflowStateBadge({ state }: { state: WorkflowJobState }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      fontFamily: SANS, fontSize: 12, fontWeight: 500, borderRadius: 999,
      padding: '3px 10px', whiteSpace: 'nowrap', ...BADGE_STYLE[state],
    }}>
      <StateIcon state={state} />
      {WORKFLOW_STATE_LABEL[state]}
    </span>
  )
}

/**
 * The one animation this workflow uses, and the escape hatch for it.
 *
 * Inline style objects cannot express @keyframes, so the rule lives here and
 * the view renders it once rather than adding a stylesheet the rest of the app
 * does not have. Under prefers-reduced-motion the sweep becomes a static bar:
 * a dozen stripes sliding at once is precisely the repetitive motion that
 * provokes vestibular symptoms, and `!important` is what lets a stylesheet
 * override the inline width and transform.
 */
export const WORKFLOW_MOTION_CSS = `
@keyframes autopivot-sweep {
  from { transform: translateX(-110%); }
  to   { transform: translateX(320%); }
}
.autopivot-sweep { animation: autopivot-sweep 1.5s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .autopivot-sweep {
    animation: none !important;
    transform: none !important;
    width: 100% !important;
    opacity: 0.5;
  }
}
`

/** An indeterminate stripe. The API reports no percentage inside a job, and
 *  inventing one would be a lie told at 2-second intervals. */
function WorkingBar() {
  return (
    <div aria-hidden style={{
      height: 3, borderRadius: 999, background: C.line, overflow: 'hidden',
    }}>
      <div className="autopivot-sweep" style={{ width: '34%', height: '100%', background: C.amber }} />
    </div>
  )
}

function plateSentence(job: ProcessingJob): string | null {
  if (job.plates_detected === null) return null
  if (job.plates_detected === 0) return 'no plates found'
  const treatment =
    job.plate_treatment === 'blur' ? 'blurred'
      : job.plate_treatment === 'pixelate' ? 'pixelated'
        : job.plate_treatment === 'white' ? 'whited out'
          : job.plate_treatment === 'overlay' ? 'overlaid'
            : job.plate_treatment === 'none' ? 'left as they are'
              : 'masked'
  return `${job.plates_detected} plate${job.plates_detected === 1 ? '' : 's'} ${treatment}`
}

function durationSentence(job: ProcessingJob): string | null {
  if (!job.started_at || !job.completed_at) return null
  const ms = Date.parse(job.completed_at) - Date.parse(job.started_at)
  if (!Number.isFinite(ms) || ms < 0) return null
  return ms < 1000 ? 'under a second' : `${(ms / 1000).toFixed(1)}s`
}

/** What the job produced, in the order a dealer cares about it. */
function producedFacts(job: ProcessingJob): string[] {
  const facts: string[] = []

  if (job.detected_angle) {
    const confidence = Number(job.angle_confidence)
    const suffix = Number.isFinite(confidence) && job.angle_confidence !== null
      ? ` · ${Math.round(confidence * 100)}% sure`
      : ''
    facts.push(`${job.detected_angle.replace(/_/g, ' ')}${suffix}`)
  }

  const plates = plateSentence(job)
  if (plates) facts.push(plates)

  const took = durationSentence(job)
  if (took) facts.push(`took ${took}`)

  return facts
}

/** Why the pipeline stood a photograph down, when the image itself explains it. */
function kindSentence(image: ListingImage | undefined): string | null {
  if (!image) return null
  if (image.image_kind === 'advertisement') {
    return 'This reads as an advertisement banner rather than a photograph of the car.'
  }
  if (image.image_kind === 'interior') return 'This is an interior shot, so there is no body to cut out.'
  if (image.image_kind === 'detail') return 'This is a close detail, so there is no body to cut out.'
  return null
}

export function WorkflowJobCard({
  job, index, image,
}: {
  job: ProcessingJob
  index: number
  /** The original photograph this job was given, when the listing has loaded. */
  image?: ListingImage
}) {
  const state = workflowJobState(job)
  const name = image?.original_filename ?? `Photograph ${index + 1}`
  // The result is the payoff, so it replaces the original the moment it
  // exists. Until then the original is what tells the dealer which car door
  // they are looking at.
  const preview = job.output_image_url ?? image?.image_url ?? null
  const showingResult = job.output_image_url !== null
  const facts = state === 'ready' ? producedFacts(job) : []
  const explanation = state === 'needs_person'
    ? [job.error_message, kindSentence(image)].filter(Boolean).join(' ')
    : state === 'failed'
      ? job.error_message ?? 'The job stopped before it produced anything.'
      : null

  return (
    <Card style={{
      overflow: 'hidden', display: 'flex', flexDirection: 'column',
      borderColor: workflowJobAccent(state),
    }}>
      {preview ? (
        <AuthedImage
          src={preview}
          alt={showingResult ? `Processed result for ${name}` : `Original photograph ${name}`}
          style={{ width: '100%', aspectRatio: '4 / 3', display: 'block', background: C.bone }}
        />
      ) : (
        <div
          aria-hidden
          style={{
            width: '100%', aspectRatio: '4 / 3', background: C.bone,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: MONO, fontSize: 11, color: C.inkSoft,
            letterSpacing: '0.08em', textTransform: 'uppercase',
          }}
        >
          No preview
        </div>
      )}

      <div style={{
        padding: '12px 14px 14px', display: 'flex', flexDirection: 'column',
        gap: 10, flex: 1,
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <div style={{ minWidth: 0 }}>
            <p style={{
              fontFamily: SANS, fontSize: 13, color: C.ink, margin: '0 0 2px',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {name}
            </p>
            <p style={{
              fontFamily: MONO, fontSize: 10, color: C.inkSoft, margin: 0,
              letterSpacing: '0.08em', textTransform: 'uppercase',
            }}>
              {String(index + 1).padStart(2, '0')} · {showingResult ? 'result' : 'original'}
            </p>
          </div>
          <WorkflowStateBadge state={state} />
        </div>

        {state === 'working' && <WorkingBar />}

        {facts.length > 0 && (
          <p style={{ fontFamily: MONO, fontSize: 11, color: C.inkSoft, margin: 0, lineHeight: 1.7 }}>
            {facts.join(' · ')}
            {job.model_used && (
              <>
                <br />
                {job.model_used}
              </>
            )}
          </p>
        )}

        {explanation && (
          <p style={{
            fontFamily: SANS, fontSize: 13, lineHeight: 1.55, margin: 0,
            color: state === 'failed' ? C.rust : C.inkSoft,
          }}>
            {explanation}
          </p>
        )}
      </div>
    </Card>
  )
}
