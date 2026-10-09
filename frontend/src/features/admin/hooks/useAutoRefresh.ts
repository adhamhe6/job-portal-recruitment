import { useCallback, useState } from 'react'

const KEY = 'talentlens.admin.autorefresh'

function read(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'off'
  } catch {
    return true
  }
}

/** Polling toggle for the monitoring console. On by default; the choice is remembered per browser (best effort). */
export function useAutoRefresh(intervalMs = 15_000) {
  const [enabled, setEnabledState] = useState(read)
  const setEnabled = useCallback((on: boolean) => {
    setEnabledState(on)
    try {
      localStorage.setItem(KEY, on ? 'on' : 'off')
    } catch {
      /* private mode: the toggle still works for this session */
    }
  }, [])
  return { enabled, setEnabled, refetchMs: enabled ? intervalMs : (false as const), intervalMs }
}
