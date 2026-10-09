import { useCallback, useSyncExternalStore } from 'react'

/**
 * Theme: 'system' (default) follows the OS; 'light' / 'dark' are explicit overrides.
 * public/theme-init.js applies the same logic before first paint (keep the storage key in sync).
 */
export type ThemePreference = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

const KEY = 'talentlens.theme'
const query = () =>
  typeof window !== 'undefined' ? window.matchMedia?.('(prefers-color-scheme: dark)') : undefined

function readPreference(): ThemePreference {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
  } catch {
    /* storage unavailable (private mode) */
  }
  return 'system'
}

function resolve(pref: ThemePreference): ResolvedTheme {
  if (pref === 'system') return query()?.matches ? 'dark' : 'light'
  return pref
}

let preference: ThemePreference = readPreference()
let resolved: ResolvedTheme = resolve(preference)
const listeners = new Set<() => void>()

function apply() {
  resolved = resolve(preference)
  document.documentElement.classList.toggle('dark', resolved === 'dark')
  document.documentElement.style.colorScheme = resolved
  listeners.forEach((l) => l())
}

export function setThemePreference(next: ThemePreference) {
  preference = next
  try {
    localStorage.setItem(KEY, next)
  } catch {
    /* ignore */
  }
  apply()
}

// Follow OS changes while the preference is 'system'.
query()?.addEventListener?.('change', () => {
  if (preference === 'system') apply()
})

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function useTheme() {
  const pref = useSyncExternalStore(
    subscribe,
    () => preference,
    () => preference,
  )
  const theme = useSyncExternalStore(
    subscribe,
    () => resolved,
    () => resolved,
  )
  const toggle = useCallback(() => setThemePreference(resolved === 'dark' ? 'light' : 'dark'), [])
  return { preference: pref, theme, setPreference: setThemePreference, toggle }
}

if (typeof document !== 'undefined') apply()
