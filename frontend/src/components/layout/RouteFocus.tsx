import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * After client-side navigation, move focus to <main> so keyboard / screen-reader users start at the new page
 * (SPA routing otherwise leaves focus on the clicked link). Query-string-only changes (filters) are ignored.
 */
export function useFocusMainOnNavigate() {
  const { pathname } = useLocation()
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    document.getElementById('main-content')?.focus({ preventScroll: true })
  }, [pathname])
}

export function SkipLink() {
  return (
    <a
      href="#main-content"
      className="sr-only z-[100] rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
    >
      Skip to main content
    </a>
  )
}
