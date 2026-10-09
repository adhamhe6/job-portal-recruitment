import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api'
import { server } from '@/test/server'
import { exportParams, exportById, ignoredFilters, EXPORTS } from '../lib/exports'
import { ExportFailedError, exportErrorMessage, runExportTask } from '../lib/exportTask'
import { weightedDaysToHire } from '../components/PipelineTab'
import { activePreset, DATE_PRESETS } from '../lib/presets'

const API = '/api/v1'
const task = (o: object) => ({
  id: 't1',
  status: 'RUNNING',
  progress: 0,
  stage: null,
  result: null,
  error_code: null,
  error_message: null,
  ...o,
})

describe('background export task', () => {
  it('queues the export, reports progress while polling and resolves with the CSV', async () => {
    let query: URLSearchParams | null = null
    const polls = [
      task({ progress: 10, stage: 'checking access' }),
      task({ progress: 80, stage: 'rendering CSV' }),
    ]
    server.use(
      http.post(`${API}/reports/job-performance/export`, ({ request }) => {
        query = new URL(request.url).searchParams
        return HttpResponse.json({ task_id: 't1', status: 'PENDING' }, { status: 202 })
      }),
      http.get(`${API}/tasks/t1`, () => {
        const next = polls.shift()
        return HttpResponse.json(
          next ??
            task({
              status: 'COMPLETED',
              progress: 100,
              result: {
                csv: 'job_id,title\r\n1,A\r\n',
                filename: 'jp.csv',
                rows: 1,
                total_rows: 1,
                truncated: false,
              },
            }),
        )
      }),
    )
    const progress = vi.fn()
    const result = await runExportTask(
      '/reports/job-performance',
      { from_date: '2026-01-01', sort: 'applications', order: 'desc' },
      { onProgress: progress, intervalMs: 5 },
    )
    expect(query!.get('from_date')).toBe('2026-01-01')
    expect(query!.get('order')).toBe('desc')
    expect(result).toEqual({
      csv: 'job_id,title\r\n1,A\r\n',
      filename: 'jp.csv',
      rows: 1,
      totalRows: 1,
      truncated: false,
    })
    expect(progress.mock.calls.map((c) => c[0])).toEqual([0, 10, 80, 100])
    expect(progress).toHaveBeenCalledWith(80, 'rendering CSV')
  })

  it('fails with the worker message when the task fails', async () => {
    server.use(
      http.post(`${API}/reports/job-performance/export`, () =>
        HttpResponse.json({ task_id: 't1', status: 'PENDING' }, { status: 202 }),
      ),
      http.get(`${API}/tasks/t1`, () =>
        HttpResponse.json(
          task({
            status: 'FAILED',
            error_code: 'EXPORT_FORBIDDEN',
            error_message: 'The requesting user can no longer export reports',
          }),
        ),
      ),
    )
    await expect(runExportTask('/reports/job-performance', {}, { intervalMs: 5 })).rejects.toMatchObject({
      message: 'The requesting user can no longer export reports',
      code: 'EXPORT_FORBIDDEN',
    })
  })

  it('stops waiting after the timeout and can be aborted', async () => {
    server.use(
      http.post(`${API}/reports/job-performance/export`, () =>
        HttpResponse.json({ task_id: 't1', status: 'PENDING' }, { status: 202 }),
      ),
      http.get(`${API}/tasks/t1`, () => HttpResponse.json(task({ progress: 5 }))),
    )
    await expect(
      runExportTask('/reports/job-performance', {}, { intervalMs: 5, timeoutMs: 30 }),
    ).rejects.toMatchObject({
      code: 'TIMEOUT',
    })
    const controller = new AbortController()
    const pending = runExportTask(
      '/reports/job-performance',
      {},
      { intervalMs: 50, signal: controller.signal },
    )
    setTimeout(() => controller.abort(), 20)
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('maps errors to plain language', () => {
    expect(exportErrorMessage(new ExportFailedError('nope', null))).toBe('nope')
    expect(exportErrorMessage(new ApiError(429, 'RATE_LIMITED', 'x'))).toMatch(/Too many exports/)
    expect(exportErrorMessage(new ApiError(403, 'FORBIDDEN', 'x'))).toMatch(/not allowed/)
    expect(exportErrorMessage(new ApiError(500, 'X', 'Server said no'))).toBe('Server said no')
    expect(exportErrorMessage('weird')).toMatch(/failed/)
  })
})

describe('export definitions', () => {
  const filters = { from: '2026-01-01', to: '2026-02-01', jobId: 'job-1' }
  it('sends only the filters each report understands', () => {
    expect(exportParams(exportById('funnel')!, filters)).toEqual({
      from_date: '2026-01-01',
      to_date: '2026-02-01',
      job_id: 'job-1',
    })
    expect(exportParams(exportById('pipeline-summary')!, filters)).toEqual({
      from_date: undefined,
      to_date: undefined,
      job_id: 'job-1',
    })
    expect(exportParams(exportById('source-statistics')!, filters)).toEqual({
      from_date: '2026-01-01',
      to_date: '2026-02-01',
      job_id: undefined,
    })
    expect(exportParams(exportById('top-skills')!, filters)).toEqual({
      from_date: undefined,
      to_date: undefined,
      job_id: undefined,
    })
  })
  it('says which active filters an export ignores', () => {
    expect(ignoredFilters(exportById('funnel')!, filters)).toBeNull()
    expect(ignoredFilters(exportById('top-skills')!, filters)).toBe('Ignores the date range and job filter')
    expect(ignoredFilters(exportById('top-skills')!, { from: '', to: '', jobId: '' })).toBeNull()
  })
  it('exports job performance in the background and the rest as a stream', () => {
    expect(exportById('job-performance')!.mode).toBe('task')
    expect(EXPORTS.filter((e) => e.mode === 'task')).toHaveLength(1)
    expect(exportById('recruiter-activity')!.hiddenFor).toContain('HIRING_MANAGER')
  })
})

describe('report helpers', () => {
  it('weights the average days to hire by the number of hires', () => {
    expect(
      weightedDaysToHire([
        { hires: 1, avg_days_to_hire: 10 },
        { hires: 3, avg_days_to_hire: 20 },
        { hires: 0, avg_days_to_hire: null },
        { hires: 2, avg_days_to_hire: null },
      ]),
    ).toBeCloseTo(17.5)
    expect(weightedDaysToHire([{ hires: 0, avg_days_to_hire: null }])).toBeNull()
  })
  it('recognises which preset is active', () => {
    const p = DATE_PRESETS.find((d) => d.id === '30')!.range()
    expect(activePreset(p.from, p.to)).toBe('30')
    expect(activePreset('', '')).toBe('all')
    expect(activePreset('2020-01-01', '2020-01-02')).toBeNull()
  })
})
