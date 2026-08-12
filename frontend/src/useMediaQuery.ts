// Breakpoint state for a codebase that styles with inline objects.
//
// Inline styles cannot carry media queries, so layout that changes with the
// viewport has to branch in JavaScript. matchMedia is the cheap way to do that:
// the browser evaluates the query, and the listener only fires when the answer
// actually changes rather than on every resize frame.

import { useEffect, useState } from 'react'

export const BREAKPOINTS = {
  /** Above this the content column is allowed to grow. */
  wide: 1600,
  /** Below this the sidebar becomes a slide-over. */
  tablet: 900,
  mobile: 640,
} as const

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
  )

  useEffect(() => {
    const list = window.matchMedia(query)
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches)
    // Re-read on mount: the query may have changed between the initial state
    // and this effect running.
    setMatches(list.matches)
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
  }, [query])

  return matches
}

export const useIsCompact = () =>
  useMediaQuery(`(max-width: ${BREAKPOINTS.tablet - 1}px)`)

export const useIsWide = () =>
  useMediaQuery(`(min-width: ${BREAKPOINTS.wide}px)`)

export const useIsMobile = () =>
  useMediaQuery(`(max-width: ${BREAKPOINTS.mobile - 1}px)`)
