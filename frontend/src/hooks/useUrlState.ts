import { useCallback, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Filter / sort / pagination state stored in the URL query string, so views are shareable, survive reloads and
 * work with back/forward. Each key is declared with a default; keys equal to their default are removed from the URL.
 *
 *   scalar:  { q: '', page: 1 }          -> string | number
 *   list:    { skill: [] as string[] }   -> repeated params (?skill=a&skill=b)
 *
 * `update(patch)` resets `page` to 1 unless the patch sets it (pass `{ resetPage: false }` to keep it).
 * Updates are applied to a ref of the latest params so several `update` calls in the same tick compose.
 */
type Scalar = string | number
export type UrlStateShape = Record<string, Scalar | string[]>

export function useUrlState<T extends UrlStateShape>(defaults: T) {
  const [params, setParams] = useSearchParams()
  const latest = useRef(params)
  latest.current = params
  const defs = useRef(defaults)

  const state = useMemo(() => {
    const out: Record<string, Scalar | string[]> = {}
    for (const [key, def] of Object.entries(defs.current)) {
      if (Array.isArray(def)) {
        const all = params.getAll(key)
        out[key] = all.length ? all : def
      } else {
        const raw = params.get(key)
        if (raw === null) out[key] = def
        else if (typeof def === 'number') {
          const n = Number(raw)
          out[key] = Number.isFinite(n) && n > 0 ? n : def
        } else out[key] = raw
      }
    }
    return out as T
  }, [params])

  const update = useCallback(
    (patch: Partial<T>, { resetPage = true, replace = true }: { resetPage?: boolean; replace?: boolean } = {}) => {
      const d = defs.current
      const next = new URLSearchParams(latest.current)
      const merged: Record<string, unknown> = { ...patch }
      if (resetPage && 'page' in d && !('page' in patch)) merged.page = d.page
      for (const [key, value] of Object.entries(merged)) {
        const def = d[key]
        next.delete(key)
        if (Array.isArray(value)) {
          if (!(Array.isArray(def) && value.length === def.length && value.every((v, i) => v === def[i]))) {
            value.forEach((v) => next.append(key, String(v)))
          }
        } else if (value !== undefined && value !== null && value !== '' && value !== def) {
          next.set(key, String(value))
        }
      }
      latest.current = next
      setParams(next, { replace })
    },
    [setParams],
  )

  const reset = useCallback(
    (keys?: (keyof T)[]) => {
      const next = new URLSearchParams(latest.current)
      for (const key of keys ?? Object.keys(defs.current)) next.delete(String(key))
      latest.current = next
      setParams(next, { replace: true })
    },
    [setParams],
  )

  return [state, update, reset] as const
}
