import { ApiError, errorFromResponse, networkError } from './errors'
import { buildQuery, type QueryParams } from './query'
import type { TokenResponse } from './types'

/**
 * Typed fetch client.
 *
 * - the access token lives in memory only (never localStorage); the refresh token is an HttpOnly cookie
 * - a 401 on an authenticated request triggers ONE silent, single-flight POST /auth/refresh, then a retry;
 *   if the refresh fails the session is declared expired (listeners: AuthProvider -> login redirect)
 * - every failure is normalised into ApiError
 */

export const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

// --- token & session events (module singletons) ------------------------------------------------------------

let accessToken: string | null = null
export const tokenStore = {
  get: () => accessToken,
  set: (token: string | null) => {
    accessToken = token
  },
}

type Listener<T> = (payload: T) => void
function emitter<T>() {
  const listeners = new Set<Listener<T>>()
  return {
    on(fn: Listener<T>) {
      listeners.add(fn)
      return () => {
        listeners.delete(fn)
      }
    },
    emit(payload: T) {
      listeners.forEach((fn) => fn(payload))
    },
  }
}
const expired = emitter<void>()
const refreshed = emitter<TokenResponse>()
/** Subscribe to "the session could not be restored" (refresh failed). */
export const onSessionExpired = expired.on
/** Subscribe to silent token refreshes performed by the client (carries the fresh user + permissions). */
export const onSessionRefreshed = refreshed.on

// --- silent refresh (single-flight) ---------------------------------------------------------------------------

let inflightRefresh: Promise<TokenResponse | null> | null = null

async function doRefresh(): Promise<TokenResponse | null> {
  const run = () =>
    fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json' },
    })
  let res: Response
  try {
    // Web Locks serialise refreshes across tabs: the refresh token is single-use and rotating, so two tabs
    // refreshing at the same instant would trip reuse detection and revoke the session.
    res =
      typeof navigator !== 'undefined' && navigator.locks
        ? await navigator.locks.request('talentlens-refresh', run)
        : await run()
  } catch {
    throw networkError()
  }
  if (res.status === 401 || res.status === 403) {
    tokenStore.set(null)
    return null
  }
  if (!res.ok) throw await errorFromResponse(res)
  const data = (await res.json()) as TokenResponse
  tokenStore.set(data.access_token)
  refreshed.emit(data)
  return data
}

/**
 * Restore / rotate the session using the refresh cookie. Concurrent callers share one request.
 * Resolves null when there is no valid session; rejects with ApiError on network / server failures.
 */
export function refreshSession(): Promise<TokenResponse | null> {
  inflightRefresh ??= doRefresh().finally(() => {
    inflightRefresh = null
  })
  return inflightRefresh
}

// --- request -------------------------------------------------------------------------------------------------------

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /** JSON body (objects) or FormData (multipart). */
  body?: unknown
  query?: QueryParams
  headers?: Record<string, string>
  signal?: AbortSignal
  /** Send/receive cookies (login, logout, refresh need it). */
  credentials?: RequestCredentials
  /** Do not attempt the silent refresh on 401 (auth endpoints). */
  skipRefresh?: boolean
}

const NO_REFRESH_PATHS = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/token']

function shouldRefresh(path: string, opts: RequestOptions, hadToken: boolean) {
  return hadToken && !opts.skipRefresh && !NO_REFRESH_PATHS.some((p) => path.startsWith(p))
}

async function send<T>(path: string, opts: RequestOptions, isRetry: boolean): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...opts.headers }
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`

  let body: BodyInit | undefined
  if (opts.body instanceof FormData) body = opts.body
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}${buildQuery(opts.query)}`, {
      method: opts.method ?? 'GET',
      headers,
      body,
      signal: opts.signal,
      credentials: opts.credentials ?? 'same-origin',
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw networkError()
  }

  if (res.status === 401 && !isRetry && shouldRefresh(path, opts, Boolean(token))) {
    let session: TokenResponse | null = null
    try {
      session = await refreshSession()
    } catch {
      /* treat as an unrecoverable session below */
    }
    if (session) return send<T>(path, opts, true)
    expired.emit()
  }

  if (!res.ok) throw await errorFromResponse(res)
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  return send<T>(path, opts, false)
}

type CallOpts = Pick<RequestOptions, 'signal' | 'headers' | 'skipRefresh' | 'credentials'>

export const api = {
  get: <T>(path: string, query?: QueryParams, opts?: CallOpts) =>
    request<T>(path, { ...opts, method: 'GET', query }),
  post: <T>(path: string, body?: unknown, opts?: CallOpts & { query?: QueryParams }) =>
    request<T>(path, { ...opts, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, opts?: CallOpts) =>
    request<T>(path, { ...opts, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, opts?: CallOpts) =>
    request<T>(path, { ...opts, method: 'PATCH', body }),
  delete: <T = void>(path: string, opts?: CallOpts) => request<T>(path, { ...opts, method: 'DELETE' }),
}

// --- multipart upload with progress (XHR: fetch has no upload progress events) ----------------------------------------

export interface UploadOptions {
  method?: 'POST' | 'PUT' | 'PATCH'
  query?: QueryParams
  onProgress?: (fraction: number) => void
  signal?: AbortSignal
}

function xhrUpload<T>(path: string, form: FormData, opts: UploadOptions, isRetry: boolean): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const token = tokenStore.get()
    xhr.open(opts.method ?? 'POST', `${API_BASE}${path}${buildQuery(opts.query)}`)
    xhr.setRequestHeader('Accept', 'application/json')
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) opts.onProgress?.(e.loaded / e.total)
    }
    xhr.onerror = () => reject(networkError())
    xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'))
    xhr.onload = async () => {
      if (xhr.status === 401 && !isRetry && token) {
        try {
          const session = await refreshSession()
          if (session) return resolve(xhrUpload<T>(path, form, opts, true))
        } catch {
          /* fall through */
        }
        expired.emit()
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        opts.onProgress?.(1)
        try {
          resolve((xhr.responseText ? JSON.parse(xhr.responseText) : undefined) as T)
        } catch {
          resolve(undefined as T)
        }
        return
      }
      reject(
        await errorFromResponse(
          new Response(xhr.responseText, {
            status: xhr.status,
            headers: { 'Content-Type': 'application/json' },
          }),
        ),
      )
    }
    if (opts.signal) {
      if (opts.signal.aborted) return reject(new DOMException('Upload aborted', 'AbortError'))
      opts.signal.addEventListener('abort', () => xhr.abort(), { once: true })
    }
    xhr.send(form)
  })
}

/** POST a multipart form with upload progress (0..1). Handles the same 401 -> refresh -> retry flow. */
export function upload<T>(path: string, form: FormData, opts: UploadOptions = {}): Promise<T> {
  return xhrUpload<T>(path, form, opts, false)
}

/** Fetch a binary/text file with auth and trigger a browser download. */
export async function downloadFile(
  path: string,
  query?: QueryParams,
  fallbackName = 'download',
): Promise<void> {
  const doFetch = () =>
    fetch(`${API_BASE}${path}${buildQuery(query)}`, {
      headers: tokenStore.get() ? { Authorization: `Bearer ${tokenStore.get()}` } : {},
    })
  let res = await doFetch().catch(() => {
    throw networkError()
  })
  if (res.status === 401 && tokenStore.get() && (await refreshSession().catch(() => null)))
    res = await doFetch()
  if (!res.ok) throw await errorFromResponse(res)
  const blob = await res.blob()
  const name =
    /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ??
    fallbackName
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = decodeURIComponent(name)
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export { ApiError }
