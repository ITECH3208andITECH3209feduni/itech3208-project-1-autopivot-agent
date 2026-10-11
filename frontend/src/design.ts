
import type { CSSProperties } from 'react'

export const C = {
  ink: '#1A1A17',
  inkSoft: '#4A4A44',
  bone: '#F5F2EC',
  paper: '#FBFAF8',
  white: '#FFFFFF',

  line: '#E2DED6',
  lineStrong: '#878580',

  forest: '#1F4D3A',
  forestLift: '#2A6B4F',
  forestTint: 'rgba(31,77,58,0.06)',

  amber: '#B8791A',
  amberTint: 'rgba(184,121,26,0.1)',
  amberText: '#936014',

  rust: '#A33A28',
  rustTint: 'rgba(163,58,40,0.1)',
}

export const SANS = "'IBM Plex Sans', system-ui, sans-serif"
export const MONO = "'IBM Plex Mono', 'Courier New', monospace"

export const CARD_SHADOW =
  '0 1px 3px rgba(26,26,23,0.06), 0 4px 12px rgba(26,26,23,0.04)'

export const RADIUS_CARD = 16
export const RADIUS_CONTROL = 10
export const CONTENT_MAX_WIDTH = 1200
export const CONTENT_MAX_WIDTH_WIDE = 1520
export const SIDEBAR_WIDTH = 240

export const serif = (size: number): CSSProperties => ({
  fontFamily: "'Fraunces', Georgia, serif",
  fontVariationSettings: `'opsz' ${size > 40 ? 144 : 72}`,
  fontWeight: 400,
  fontSize: size,
})

export const UNSPLASH = (id: string, w = 900, h = 600) =>
  `https://images.unsplash.com/${id}?w=${w}&h=${h}&fit=crop&auto=format`
