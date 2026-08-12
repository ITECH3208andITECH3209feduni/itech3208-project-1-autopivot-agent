// AutoPivot Agent — design tokens.
//
// The single source of truth for the visual system. The brand guidelines are a
// transcription of this file; where the two disagree, this file is correct.
//
// Everything that draws UI imports from here. The Figma Make export duplicated
// these values inline in App.tsx and again in Guidelines.tsx, which is exactly
// the drift the guidelines were written to prevent — and it had already begun.

import type { CSSProperties } from 'react'

export const C = {
  ink: '#1A1A17',
  inkSoft: '#4A4A44',
  bone: '#F5F2EC',
  paper: '#FBFAF8',
  white: '#FFFFFF',

  line: '#E2DED6',
  // Guidelines §10: line on paper measures 1.29:1. That is fine for decorative
  // dividers, which WCAG exempts, but it fails 1.4.11 for the boundary of an
  // interactive component. Inputs and controls use this darker variant (3.53:1).
  lineStrong: '#878580',

  forest: '#1F4D3A',
  forestLift: '#2A6B4F',
  forestTint: 'rgba(31,77,58,0.06)',

  amber: '#B8791A',
  amberTint: 'rgba(184,121,26,0.1)',
  // Guidelines §10: amber on amber-tint measures 3.12:1, which passes for large
  // text but fails body text. This darker variant reaches 4.60:1 and is what the
  // "Processing" pill label uses. Plain `amber` is still correct for the
  // progress track, where 3:1 suffices.
  amberText: '#936014',

  rust: '#A33A28',
  rustTint: 'rgba(163,58,40,0.1)',
}

export const SANS = "'IBM Plex Sans', system-ui, sans-serif"
export const MONO = "'IBM Plex Mono', 'Courier New', monospace"

export const CARD_SHADOW =
  '0 1px 3px rgba(26,26,23,0.06), 0 4px 12px rgba(26,26,23,0.04)'

// Surface constants from guidelines §7. Values outside the 8px spacing scale
// are a mistake, not a decision.
export const RADIUS_CARD = 16
export const RADIUS_CONTROL = 10
export const CONTENT_MAX_WIDTH = 1200
export const SIDEBAR_WIDTH = 240

/**
 * Fraunces at a given size, with the optical size axis tracked to it.
 *
 * Higher opsz means higher stroke contrast. Encoding the rule here rather than
 * documenting it means the defect that produced it — hairlines that nearly
 * vanished when opsz 144 was applied at 14px — cannot recur by accident.
 *
 * Fraunces is display only: never below 24px, never body, never interface.
 */
export const serif = (size: number): CSSProperties => ({
  fontFamily: "'Fraunces', Georgia, serif",
  fontVariationSettings: `'opsz' ${size > 40 ? 144 : 72}`,
  fontWeight: 400,
  fontSize: size,
})

/**
 * Placeholder photography.
 *
 * These are Unsplash stock images carried over from the design prototype. They
 * are not AutoPivot output and several backdrop variants resolve to the same
 * photograph, so the landing configurator does not yet demonstrate backdrop
 * switching. Replacing them with real pipeline renders is tracked separately.
 */
export const UNSPLASH = (id: string, w = 900, h = 600) =>
  `https://images.unsplash.com/${id}?w=${w}&h=${h}&fit=crop&auto=format`
