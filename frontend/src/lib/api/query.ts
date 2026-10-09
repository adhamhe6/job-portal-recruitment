export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue | ReadonlyArray<QueryValue>>

/**
 * Build a query string. Arrays become repeated params (`?skill=a&skill=b`, what FastAPI list params expect);
 * null / undefined / empty-string values are dropped. Returns '' or a string starting with '?'.
 */
export function buildQuery(params?: QueryParams): string {
  if (!params) return ''
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    const values = Array.isArray(value) ? value : [value]
    for (const v of values as QueryValue[]) {
      if (v === undefined || v === null || v === '') continue
      sp.append(key, String(v))
    }
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}
