import { useSyncExternalStore } from 'react'

/** Subscribe to a CSS media query. SSR/test-safe: returns `fallback` when matchMedia is unavailable. */
export function useMediaQuery(query: string, fallback = false): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === 'undefined' || !window.matchMedia) return () => {}
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(query).matches : fallback),
    () => fallback,
  )
}

/** md breakpoint and up (>= 768px). */
export const useIsDesktop = () => useMediaQuery('(min-width: 768px)', true)
