// Switches between the public coming-soon page and the in-progress landing
// page. Backed by routes rather than component state, so either view can be
// linked to directly and survives a refresh.

import { useNavigate } from 'react-router-dom'

import { C, MONO } from '../design'

type Side = 'coming-soon' | 'preview'

const OPTIONS: { side: Side; label: string; to: string }[] = [
  { side: 'coming-soon', label: 'Coming soon', to: '/' },
  { side: 'preview', label: 'Preview', to: '/preview' },
]

export default function PreviewToggle({
  current,
  onDark = current === 'coming-soon',
}: {
  current: Side
  onDark?: boolean
}) {
  const navigate = useNavigate()

  // The coming-soon page is ink; the landing page is bone. The control has to
  // read on both, so the palette flips rather than the layout.
  const idle = onDark ? 'rgba(245,242,236,0.45)' : C.inkSoft
  const activeText = onDark ? C.ink : C.white
  const activeBg = onDark ? C.bone : C.forest
  const border = onDark ? 'rgba(226,222,214,0.2)' : C.line

  return (
    <div
      role="group"
      aria-label="Site view"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 2, padding: 3,
        border: `1px solid ${border}`, borderRadius: 999,
      }}
    >
      {OPTIONS.map(option => {
        const isActive = option.side === current
        return (
          <button
            key={option.side}
            onClick={() => navigate(option.to)}
            aria-current={isActive ? 'page' : undefined}
            style={{
              fontFamily: MONO, fontSize: 10, letterSpacing: '0.08em',
              textTransform: 'uppercase', border: 'none', borderRadius: 999,
              padding: '5px 12px', cursor: 'pointer',
              color: isActive ? activeText : idle,
              background: isActive ? activeBg : 'transparent',
              transition: 'background 0.15s, color 0.15s',
            }}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
