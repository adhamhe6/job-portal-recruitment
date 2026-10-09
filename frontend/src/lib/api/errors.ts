/** Normalised API error. Every non-2xx response (and network failure) is turned into one of these. */

export interface FieldIssue {
  field: string
  message: string
  type?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly requestId: string | null

  constructor(status: number, code: string, message: string, details?: unknown, requestId?: string | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details ?? null
    this.requestId = requestId ?? null
  }

  is(...codes: string[]): boolean {
    return codes.includes(this.code)
  }

  get isNetworkError(): boolean {
    return this.status === 0
  }

  /** Pydantic-style issues from a 422 VALIDATION_ERROR: [{field, message, type}]. */
  get fieldIssues(): FieldIssue[] {
    if (!Array.isArray(this.details)) return []
    const out: FieldIssue[] = []
    for (const d of this.details as unknown[]) {
      if (d && typeof d === 'object' && 'message' in d && typeof (d as FieldIssue).message === 'string') {
        const issue = d as Partial<FieldIssue>
        out.push({
          field: issue.field ?? '',
          message: cleanMessage(issue.message ?? ''),
          type: issue.type,
        })
      }
    }
    return out
  }

  /** Field -> first message map for VALIDATION_ERROR (field paths like "skills.0" are kept as sent). */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {}
    for (const i of this.fieldIssues) {
      if (i.field && !(i.field in out)) out[i.field] = i.message
    }
    return out
  }

  /** Plain string list details, e.g. PUBLISH_VALIDATION_FAILED -> ["Add at least one required skill"]. */
  get detailMessages(): string[] {
    if (!Array.isArray(this.details)) return []
    return (this.details as unknown[]).filter((d): d is string => typeof d === 'string')
  }
}

/** Pydantic prefixes custom validator messages with "Value error, ". */
function cleanMessage(msg: string): string {
  return msg.replace(/^Value error,\s*/i, '').replace(/^Assertion failed,\s*/i, '')
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError
}

export function errorMessage(e: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error && e.message) return e.message
  return fallback
}

/** Build an ApiError from a (non-ok) fetch Response. */
export async function errorFromResponse(res: Response): Promise<ApiError> {
  type Body = { error?: { code?: string; message?: string; details?: unknown; request_id?: string | null } }
  let body: Body | null = null
  try {
    body = (await res.json()) as Body
  } catch {
    /* non-JSON error body (proxy / gateway page) */
  }
  const fallback =
    res.status >= 500
      ? 'The server is temporarily unavailable. Please try again.'
      : res.status === 404
        ? 'The requested resource was not found.'
        : res.status === 429
          ? 'Too many requests. Please wait a moment and try again.'
          : `Request failed (${res.status})`
  return new ApiError(
    res.status,
    body?.error?.code ?? `HTTP_${res.status}`,
    body?.error?.message ?? fallback,
    body?.error?.details,
    body?.error?.request_id ?? res.headers.get('x-request-id'),
  )
}

export const networkError = () =>
  new ApiError(0, 'NETWORK_ERROR', 'Cannot reach the server. Check your connection and try again.')
