import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { errorBody } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { jobPerformance, jobRow, lastCall, mockReports } from './fixtures'

const API = '/api/v1'

let saved: { href: string; download: string }[] = []
beforeEach(() => {
  saved = []
  URL.createObjectURL = vi.fn(() => 'blob:report')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    saved.push({ href: this.href, download: this.download })
  })
})
afterEach(() => vi.restoreAllMocks())

/** The KPI tile whose label is `label` (labels like "Applications" also appear in tables and chart titles). */
const kpiCard = (label: string) =>
  screen
    .getAllByText(label)
    .find((el) => el.tagName === 'P' && el.className.includes('text-muted-foreground'))!
    .closest('div[class*="p-5"]') as HTMLElement

describe('reports page — overview', () => {
  it('shows KPIs, the funnel with conversion, and status distribution', async () => {
    signInAs('RECRUITER')
    mockReports()
    renderApp('/reports')
    expect(await screen.findByRole('heading', { level: 1, name: 'Reports' })).toBeInTheDocument()
    const kpi = kpiCard
    await waitFor(() => expect(kpi('Applications')).toHaveTextContent('15'))
    expect(kpi('Hired')).toHaveTextContent('13.3% of applications')
    expect(kpi('Active in pipeline')).toHaveTextContent('11')
    expect(kpi('Waiting too long')).toHaveTextContent('No change for over 14 days')

    const table = await screen.findByRole('table', { name: 'Hiring funnel by stage' })
    const screening = within(table).getByText('Screening').closest('tr')!
    expect(
      within(screening)
        .getAllByRole('cell')
        .map((c) => c.textContent),
    ).toEqual(['Screening', '10', '66.7%', '66.7%'])
    expect(within(table).getByText('Withdrawn').closest('tr')).toHaveTextContent('Branch')
    // the chart is exposed with a text alternative
    expect(
      screen.getByRole('img', { name: /Hiring funnel\. Applied: 15 · 100%; Screening: 10 · 66.7%/ }),
    ).toBeInTheDocument()
    // and the status chart has a data table for screen readers
    expect(screen.getByRole('table', { name: 'Applications by current status' })).toBeInTheDocument()
  })

  it('has an empty funnel state when nothing was received in the period', async () => {
    signInAs('RECRUITER')
    mockReports({
      funnel: () => HttpResponse.json({ period: {}, job_id: null, applications: 0, stages: [] }),
    })
    renderApp('/reports')
    expect(await screen.findByText('No applications in this period')).toBeInTheDocument()
  })

  it('shows a per-card error with retry while other cards keep working', async () => {
    signInAs('RECRUITER')
    let fail = true
    mockReports({
      funnel: () =>
        fail
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(jobFunnel()),
    })
    const { user } = renderApp('/reports')
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.length).toBeGreaterThan(0)
    expect(await screen.findByRole('heading', { name: 'Applications by current status' })).toBeInTheDocument()
    fail = false
    await user.click(screen.getAllByRole('button', { name: /Try again/ })[0]!)
    expect(await screen.findByRole('table', { name: 'Hiring funnel by stage' })).toBeInTheDocument()
  })
})

function jobFunnel() {
  return {
    period: {},
    job_id: 'job-1',
    applications: 7,
    stages: [{ stage: 'APPLIED', count: 7, pct_of_applied: 100, pct_of_previous: null, is_branch: false }],
  }
}

describe('reports page — filters live in the URL', () => {
  it('applies a date preset and a job to the requests that understand them', async () => {
    signInAs('RECRUITER')
    const calls = mockReports()
    const { user, router } = renderApp('/reports')
    await screen.findByRole('table', { name: 'Hiring funnel by stage' })
    expect(lastCall(calls, 'funnel').has('from_date')).toBe(false)
    expect(screen.getByRole('button', { name: 'All time' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: 'Last 90 days' }))
    await waitFor(() => expect(lastCall(calls, 'funnel').get('from_date')).toMatch(/^\d{4}-\d{2}-\d{2}$/))
    const params = lastCall(calls, 'funnel')
    expect(params.get('to_date')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(router.state.location.search).toContain(`from=${params.get('from_date')}`)
    expect(screen.getByRole('button', { name: 'Last 90 days' })).toHaveAttribute('aria-pressed', 'true')

    await user.selectOptions(screen.getByLabelText('Job'), 'job-1')
    await waitFor(() => expect(lastCall(calls, 'funnel').get('job_id')).toBe('job-1'))
    expect(lastCall(calls, 'applications-by-status').get('job_id')).toBe('job-1')
    // the pipeline snapshot takes the job but never a date window
    await waitFor(() => expect(lastCall(calls, 'pipeline-summary').get('job_id')).toBe('job-1'))
    expect(lastCall(calls, 'pipeline-summary').has('from_date')).toBe(false)
    expect(router.state.location.search).toContain('job=job-1')

    // removable chips + clear all
    expect(screen.getByRole('list', { name: 'Active filters' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear all' }))
    await waitFor(() => expect(lastCall(calls, 'funnel').has('job_id')).toBe(false))
    expect(lastCall(calls, 'funnel').has('from_date')).toBe(false)
  })

  it('restores filters and the selected tab from the URL', async () => {
    signInAs('RECRUITER')
    const calls = mockReports()
    renderApp('/reports?tab=jobs&from=2026-01-01&to=2026-03-31&sort=hire_rate&order=asc&page=1')
    await screen.findByRole('table', { name: 'Job performance' })
    const p = lastCall(calls, 'job-performance')
    expect(p.get('from_date')).toBe('2026-01-01')
    expect(p.get('to_date')).toBe('2026-03-31')
    expect(p.get('sort')).toBe('hire_rate')
    expect(p.get('order')).toBe('asc')
    expect(screen.getByRole('tab', { name: 'Job performance' })).toHaveAttribute('aria-selected', 'true')
    expect((screen.getByLabelText('From') as HTMLInputElement).value).toBe('2026-01-01')
  })

  it('ignores an inverted date range and says so', async () => {
    signInAs('RECRUITER')
    const calls = mockReports()
    renderApp('/reports?from=2026-06-01&to=2026-05-01')
    expect(await screen.findByText('Check the date range')).toBeInTheDocument()
    await screen.findByRole('table', { name: 'Hiring funnel by stage' })
    expect(lastCall(calls, 'funnel').has('from_date')).toBe(false)
  })
})

describe('reports page — sections', () => {
  it('lists job performance with sortable columns and links', async () => {
    signInAs('RECRUITER')
    const calls = mockReports()
    const { user, router } = renderApp('/reports')
    await user.click(await screen.findByRole('tab', { name: 'Job performance' }))
    const table = await screen.findByRole('table', { name: 'Job performance' })
    const row = within(table).getByRole('link', { name: 'Senior Backend Engineer' }).closest('tr')!
    expect(
      within(row).getByRole('link', { name: '7 applications for Senior Backend Engineer' }),
    ).toHaveAttribute('href', '/applications?job_id=job-1')
    expect(row).toHaveTextContent('29%')
    expect(row).toHaveTextContent('12 d')
    expect(lastCall(calls, 'job-performance').get('sort')).toBe('applications')
    expect(lastCall(calls, 'job-performance').get('order')).toBe('desc')

    await user.click(within(table).getByRole('button', { name: /Days to hire/ }))
    await waitFor(() => expect(lastCall(calls, 'job-performance').get('sort')).toBe('avg_days_to_hire'))
    expect(router.state.location.search).toContain('sort=avg_days_to_hire')
    await user.click(
      within(await screen.findByRole('table', { name: 'Job performance' })).getByRole('button', {
        name: /Days to hire/,
      }),
    )
    await waitFor(() => expect(lastCall(calls, 'job-performance').get('order')).toBe('asc'))
  })

  it('paginates the job table and shows an empty state', async () => {
    signInAs('RECRUITER')
    const many = Array.from({ length: 10 }, (_, i) => jobRow({ job_id: `j${i}`, title: `Job ${i}` }))
    const calls = mockReports({
      'job-performance': () => HttpResponse.json({ ...jobPerformance(many), total: 25, pages: 3 }),
    })
    const { user } = renderApp('/reports?tab=jobs')
    await screen.findByRole('link', { name: 'Job 0' })
    await user.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => expect(lastCall(calls, 'job-performance').get('page')).toBe('2'))
  })

  it('shows an empty state when no job received applications', async () => {
    signInAs('RECRUITER')
    mockReports({ 'job-performance': () => HttpResponse.json(jobPerformance([])) })
    renderApp('/reports?tab=jobs')
    expect(await screen.findByText('No jobs received applications')).toBeInTheDocument()
  })

  it('shows time-in-stage, time to hire and the stage table on the pipeline tab', async () => {
    signInAs('RECRUITER')
    mockReports()
    const { user } = renderApp('/reports')
    await user.click(await screen.findByRole('tab', { name: 'Pipeline & timing' }))
    expect(await screen.findByText('Avg. days to hire')).toBeInTheDocument()
    await waitFor(() => expect(kpiCard('Avg. days to hire')).toHaveTextContent('12 d'))
    const table = await screen.findByRole('table', { name: 'Applications and time in stage' })
    const applied = within(table).getByText('Applied').closest('tr')!
    expect(applied).toHaveTextContent('9.6 d')
    expect(applied).toHaveTextContent('17.2 d')
    expect(screen.getByRole('img', { name: /Time in current stage/ })).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: /Days to hire by job\. Senior Backend Engineer: 12 days/ }),
    ).toBeInTheDocument()
  })

  it('shows sources and skills demand vs supply', async () => {
    signInAs('RECRUITER')
    mockReports()
    const { user } = renderApp('/reports')
    await user.click(await screen.findByRole('tab', { name: 'Sources & skills' }))
    const table = await screen.findByRole('table', { name: 'Application sources' })
    expect(within(table).getByText('Referral').closest('tr')).toHaveTextContent('3')
    expect(
      await screen.findByRole('img', { name: /Most requested skills\. Python: 3 jobs/ }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: /Most common applicant skills\. Python: 10 candidates/ }),
    ).toBeInTheDocument()
    expect(screen.getByText(/your company’s published jobs/)).toBeInTheDocument()
  })

  it('shows interview and matching statistics', async () => {
    signInAs('RECRUITER')
    mockReports()
    const { user } = renderApp('/reports')
    await user.click(await screen.findByRole('tab', { name: 'Interviews & matching' }))
    const kpi = kpiCard
    await waitFor(() => expect(kpi('Interviews')).toHaveTextContent('8'))
    expect(kpi('No-show rate')).toHaveTextContent('17%')
    expect(kpi('Average length')).toHaveTextContent('55 min')
    expect(kpi('Avg. feedback rating')).toHaveTextContent('4.3 / 5')
    expect(
      await screen.findByRole('table', { name: 'Average match score by application outcome' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/relevance aid, not a prediction/)).toBeInTheDocument()
  })
})

describe('reports page — CSV export', () => {
  it('downloads a streamed report with the active filters and confirms it', async () => {
    signInAs('RECRUITER')
    mockReports()
    let query: URLSearchParams | null = null
    server.use(
      http.get(`${API}/reports/funnel`, ({ request }) => {
        const u = new URL(request.url)
        if (u.searchParams.get('format') === 'csv') {
          query = u.searchParams
          return new HttpResponse('stage,count\r\nAPPLIED,15\r\n', {
            headers: {
              'Content-Type': 'text/csv; charset=utf-8',
              'Content-Disposition': 'attachment; filename="talentlens-funnel-20261009.csv"',
            },
          })
        }
        return HttpResponse.json(jobFunnel())
      }),
    )
    const { user } = renderApp('/reports?from=2026-01-01&to=2026-03-31&job=job-1')
    await user.click(await screen.findByRole('button', { name: 'Export CSV' }))
    await user.click(await screen.findByRole('menuitem', { name: /Hiring funnel/ }))
    await waitFor(() => expect(query).not.toBeNull())
    expect(query!.get('format')).toBe('csv')
    expect(query!.get('from_date')).toBe('2026-01-01')
    expect(query!.get('job_id')).toBe('job-1')
    expect(await screen.findByText('Hiring funnel', { selector: 'strong' })).toBeInTheDocument()
    expect(saved).toEqual([{ href: 'blob:report', download: 'talentlens-funnel-20261009.csv' }])
  })

  it('exports job performance as a background task with progress, then downloads it', async () => {
    signInAs('RECRUITER')
    mockReports()
    let posted: URLSearchParams | null = null
    let polls = 0
    server.use(
      http.post(`${API}/reports/job-performance/export`, ({ request }) => {
        posted = new URL(request.url).searchParams
        return HttpResponse.json({ task_id: 't1', status: 'PENDING' }, { status: 202 })
      }),
      http.get(`${API}/tasks/t1`, () => {
        polls += 1
        return HttpResponse.json(
          polls === 1
            ? {
                id: 't1',
                status: 'RUNNING',
                progress: 40,
                stage: 'querying',
                result: null,
                error_code: null,
                error_message: null,
              }
            : {
                id: 't1',
                status: 'COMPLETED',
                progress: 100,
                stage: null,
                result: {
                  csv: 'job_id,title\r\n',
                  filename: 'talentlens-job-performance.csv',
                  rows: 1000,
                  total_rows: 1500,
                  truncated: true,
                },
                error_code: null,
                error_message: null,
              },
        )
      }),
    )
    const { user } = renderApp('/reports?tab=jobs&from=2026-01-01&sort=hire_rate&order=asc')
    await screen.findByRole('table', { name: 'Job performance' })
    await user.click(screen.getAllByRole('button', { name: 'Export CSV' })[1]!)
    const progress = await screen.findByRole('progressbar', { name: /Export progress, 40 percent/ })
    expect(progress).toBeInTheDocument()
    expect(posted!.get('from_date')).toBe('2026-01-01')
    expect(posted!.get('sort')).toBe('hire_rate')
    expect(posted!.get('order')).toBe('asc')
    expect(
      await screen.findByText('talentlens-job-performance.csv', {}, { timeout: 5000 }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Only the first 1000 of 1500 rows/)).toBeInTheDocument()
    expect(saved).toEqual([{ href: 'blob:report', download: 'talentlens-job-performance.csv' }])
  })

  it('reports a failed export and lets the user retry', async () => {
    signInAs('RECRUITER')
    mockReports()
    let fail = true
    server.use(
      http.get(`${API}/reports/source-statistics`, ({ request }) => {
        if (new URL(request.url).searchParams.get('format') !== 'csv')
          return HttpResponse.json({ items: [], page: 1, page_size: 20, total: 0, pages: 0, period: {} })
        return fail
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'Export exploded'), { status: 500 })
          : new HttpResponse('source\r\n', { headers: { 'Content-Type': 'text/csv' } })
      }),
    )
    const { user } = renderApp('/reports')
    await user.click(await screen.findByRole('button', { name: 'Export CSV' }))
    await user.click(await screen.findByRole('menuitem', { name: /Application sources/ }))
    const alert = await screen.findByText(/Export failed: Application sources/)
    expect(alert.closest('[role="alert"]')).toHaveTextContent(/temporarily unavailable|Export exploded/)
    expect(saved).toHaveLength(0)
    fail = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Application sources', { selector: 'strong' })).toBeInTheDocument()
    expect(saved).toHaveLength(1)
  })

  it('surfaces a failed background export', async () => {
    signInAs('RECRUITER')
    mockReports()
    server.use(
      http.post(`${API}/reports/job-performance/export`, () =>
        HttpResponse.json(errorBody('RATE_LIMITED', 'slow down'), { status: 429 }),
      ),
    )
    const { user } = renderApp('/reports')
    await user.click(await screen.findByRole('button', { name: 'Export CSV' }))
    await user.click(await screen.findByRole('menuitem', { name: /Job performance/ }))
    expect(await screen.findByText(/Export failed: Job performance/)).toBeInTheDocument()
    expect(screen.getByText(/Too many exports in a short time/)).toBeInTheDocument()
  })

  it('tells which filters an export ignores and hides reports a hiring manager may not export', async () => {
    signInAs('HIRING_MANAGER')
    mockReports()
    const { user } = renderApp('/reports?from=2026-01-01')
    await user.click(await screen.findByRole('button', { name: 'Export CSV' }))
    const menu = await screen.findByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: /Pipeline summary/ })).toHaveTextContent(
      'Ignores the date range filter',
    )
    expect(within(menu).queryByRole('menuitem', { name: /Recruiter activity/ })).not.toBeInTheDocument()
    expect(within(menu).getByRole('menuitem', { name: /Hiring funnel/ })).toBeInTheDocument()
  })
})
