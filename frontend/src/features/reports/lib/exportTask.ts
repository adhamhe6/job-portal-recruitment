import { api, ApiError, type QueryParams } from '@/lib/api'

/** Poll cadence for background exports (the worker reports progress every few hundred ms). */
export const POLL_INTERVAL_MS = 1000
/** The backend gives an export task 300 s; stop waiting a little later. */
export const POLL_TIMEOUT_MS = 330_000

interface TaskRef {
  task_id: string
  status: string
}

export interface TaskOut {
  id: string
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  progress: number
  stage: string | null
  result: Record<string, unknown> | null
  error_code: string | null
  error_message: string | null
}

export interface ExportResult {
  csv: string
  filename: string
  rows: number | null
  totalRows: number | null
  truncated: boolean
}

export class ExportFailedError extends Error {
  readonly code: string | null

  constructor(message: string, code: string | null) {
    super(message)
    this.name = 'ExportFailedError'
    this.code = code
  }
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const t = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(t)
        reject(new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })

/**
 * Queue a report export and wait for it: POST …/export -> 202 { task_id } -> poll GET /tasks/{id} until the task is
 * COMPLETED (the CSV text is in `result.csv`) or FAILED. `onProgress` receives 0..100 and the worker's stage name.
 */
export async function runExportTask(
  path: string,
  query: QueryParams,
  {
    onProgress,
    signal,
    intervalMs = POLL_INTERVAL_MS,
    timeoutMs = POLL_TIMEOUT_MS,
  }: {
    onProgress?: (percent: number, stage: string | null) => void
    signal?: AbortSignal
    intervalMs?: number
    timeoutMs?: number
  } = {},
): Promise<ExportResult> {
  const ref = await api.post<TaskRef>(`${path}/export`, undefined, { query, signal })
  const deadline = Date.now() + timeoutMs
  onProgress?.(0, 'queued')
  for (;;) {
    const task = await api.get<TaskOut>(`/tasks/${ref.task_id}`, undefined, { signal })
    if (task.status === 'COMPLETED') {
      const r = task.result ?? {}
      if (typeof r.csv !== 'string') throw new ExportFailedError('The export finished without a file.', null)
      onProgress?.(100, null)
      return {
        csv: r.csv,
        filename: typeof r.filename === 'string' ? r.filename : 'report.csv',
        rows: typeof r.rows === 'number' ? r.rows : null,
        totalRows: typeof r.total_rows === 'number' ? r.total_rows : null,
        truncated: r.truncated === true,
      }
    }
    if (task.status === 'FAILED')
      throw new ExportFailedError(task.error_message ?? 'The export failed.', task.error_code)
    onProgress?.(task.progress, task.stage)
    if (Date.now() >= deadline)
      throw new ExportFailedError('The export is taking longer than expected. Please try again later.', 'TIMEOUT')
    await sleep(intervalMs, signal)
  }
}

/** Save text as a file download (Blob + temporary link). */
export function saveTextFile(text: string, filename: string, type = 'text/csv;charset=utf-8'): void {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError'

export function exportErrorMessage(e: unknown): string {
  if (e instanceof ExportFailedError) return e.message
  if (e instanceof ApiError) {
    if (e.status === 429) return 'Too many exports in a short time. Please wait a moment and try again.'
    if (e.status === 403) return 'Your account is not allowed to export this report.'
    return e.message
  }
  return e instanceof Error ? e.message : 'The export failed. Please try again.'
}
