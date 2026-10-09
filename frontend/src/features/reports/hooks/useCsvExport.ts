import { useCallback, useEffect, useRef, useState } from 'react'
import { downloadFile } from '@/lib/api'
import type { ReportFilters } from '../api/types'
import { exportParams, type ExportDef } from '../lib/exports'
import { exportErrorMessage, isAbort, runExportTask, saveTextFile } from '../lib/exportTask'

export type ExportState =
  | { status: 'idle' }
  | { status: 'running'; def: ExportDef; progress: number | null; stage: string | null }
  | { status: 'done'; def: ExportDef; filename: string | null; note: string | null }
  | { status: 'error'; def: ExportDef; message: string }

/**
 * CSV exports. Streamed reports download straight away (`?format=csv`); job performance is queued as a background
 * task, polled with progress, then saved. One export at a time; unmounting cancels polling.
 */
export function useCsvExport(filters: ReportFilters, sort?: { sort: string; order: 'asc' | 'desc' }) {
  const [state, setState] = useState<ExportState>({ status: 'idle' })
  const abort = useRef<AbortController | null>(null)

  useEffect(() => () => abort.current?.abort(), [])

  const start = useCallback(
    async (def: ExportDef) => {
      abort.current?.abort()
      const controller = new AbortController()
      abort.current = controller
      const params = exportParams(def, filters)
      setState({ status: 'running', def, progress: def.mode === 'task' ? 0 : null, stage: null })
      try {
        if (def.mode === 'task') {
          const result = await runExportTask(
            def.path,
            { ...params, ...(sort ?? {}) },
            {
              signal: controller.signal,
              onProgress: (progress, stage) => setState({ status: 'running', def, progress, stage }),
            },
          )
          saveTextFile(result.csv, result.filename)
          setState({
            status: 'done',
            def,
            filename: result.filename,
            note: result.truncated
              ? `Only the first ${result.rows} of ${result.totalRows} rows are included. Narrow the date range for the rest.`
              : null,
          })
        } else {
          await downloadFile(def.path, { ...params, format: 'csv' }, `${def.id}.csv`)
          setState({ status: 'done', def, filename: null, note: null })
        }
      } catch (e) {
        if (isAbort(e) || controller.signal.aborted) return
        setState({ status: 'error', def, message: exportErrorMessage(e) })
      }
    },
    [filters, sort],
  )

  const dismiss = useCallback(() => setState({ status: 'idle' }), [])
  return { state, start, dismiss, busy: state.status === 'running' }
}
