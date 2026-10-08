
import { useEffect, useState } from 'react'

export const BREAKPOINTS = {
  wide: 1600,
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
