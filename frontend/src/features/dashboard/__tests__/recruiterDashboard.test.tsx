import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import type { RecruiterDashboardData } from '../api/dashboard'

const DASH: RecruiterDashboardData = {
  scope: 'company',
  company_id: 'c1',
  period: { from_date: '2026-09-10', to_date: '2026-10-09', granularity: 'day' },
  generated_at: new Date().toISOString(),
  kpis: {
    active_jobs: 5,
    total_applications: 14,
    applications_in_screening: 3,
    shortlisted: 2,
    upcoming_interviews: 4,
    jobs_nearing_deadline: 1,
    avg_applications_per_job: 2.8,
    hires_in_period: 1,
  },
  funnel: [
    { stage: 'APPLIED', count: 14, pct_of_applied: 100, pct_of_previous: null, is_branch: false },
    { stage: 'SCREENING', count: 9, pct_of_applied: 64.3, pct_of_previous: 64.3, is_branch: false },
    { stage: 'HIRED', count: 1, pct_of_applied: 7.1, pct_of_previous: 50, is_branch: false },
    { stage: 'REJECTED', count: 2, pct_of_applied: 14.3, pct_of_previous: null, is_branch: true },
  ],
  applications_over_time: [
    { bucket: '2026-10-07', count: 2 },
    { bucket: '2026-10-08', count: 0 },
  ],
  applications_by_job: [
    { job_id: 'job-1', title: 'Senior Backend Engineer', job_status: 'PUBLISHED', applications: 7 },
    { job_id: 'job-2', title: 'Data Analyst', job_status: 'PUBLISHED', applications: 2 },
  ],
  status_distribution: [
    { status: 'APPLIED', count: 4, percent: 28.6 },
    { status: 'SCREENING', count: 3, percent: 21.4 },
  ],
  top_matching_candidates: [],
  recent_applications: [
    {
      id: 'app-9',
      candidate_id: 'cand-1',
      candidate_name: 'Dmitri Volkov',
      job_id: 'job-1',
      job_title: 'DevOps Engineer',
      status: 'SCREENING',
      applied_at: new Date(Date.now() - 3_600_000).toISOString(),
      match_score: 0.9,
      match_band: 'STRONG',
    },
  ],
}

const INTERVIEWS = page([
  {
    id: 'iv-1',
    application_id: 'app-9',
    job_title: 'DevOps Engineer',
    candidate_name: 'Bianca Costa',
    interview_type: 'TECHNICAL',
    start_at: '2026-10-12T09:00:00Z',
    end_at: '2026-10-12T10:00:00Z',
    timezone: 'UTC',
    status: 'CONFIRMED',
  },
])

function handlers(dash: RecruiterDashboardData = DASH, interviews = INTERVIEWS) {
  const calls: URLSearchParams[] = []
  server.use(
    http.get('/api/v1/reports/recruiter-dashboard', ({ request }) => {
      calls.push(new URL(request.url).searchParams)
      return HttpResponse.json(dash)
    }),
    http.get('/api/v1/interviews', () => HttpResponse.json(interviews)),
  )
  return calls
}

describe('recruiter dashboard', () => {
  it('renders KPIs, funnel, top jobs, upcoming interviews and recent applications from the report', async () => {
    signInAs('RECRUITER')
    handlers()
    renderApp('/dashboard')
    expect(await screen.findByRole('heading', { level: 1, name: /Welcome back, Riley/ })).toBeInTheDocument()
    const kpis = await screen.findByRole('region', { name: 'Key figures' })
    expect(await within(kpis).findByRole('link', { name: /Open jobs\s*5/ })).toHaveAttribute(
      'href',
      '/manage/jobs',
    )
    expect(within(kpis).getByRole('link', { name: /Applications\s*14/ })).toBeInTheDocument()
    expect(within(kpis).getByRole('link', { name: /Shortlisted\s*2/ })).toHaveAttribute(
      'href',
      '/applications?status=SHORTLISTED',
    )
    expect(within(kpis).getByRole('link', { name: /Interviews this week\s*4/ })).toBeInTheDocument()
    expect(within(kpis).getByRole('link', { name: /Hires\s*1/ })).toBeInTheDocument()
    expect(within(kpis).getByText('1 closing within 7 days')).toBeInTheDocument()

    const funnel = await screen.findByRole('list', { name: 'Funnel stages' })
    expect(within(funnel).getByText(/64.3% of previous/)).toBeInTheDocument()
    expect(screen.getByText(/Rejected:/)).toBeInTheDocument()

    expect(screen.getByRole('link', { name: 'Senior Backend Engineer: 7 applications' })).toHaveAttribute(
      'href',
      '/applications?job_id=job-1',
    )
    expect(await screen.findByRole('link', { name: 'Bianca Costa' })).toHaveAttribute(
      'href',
      '/interviews/iv-1',
    )
    expect(screen.getByRole('link', { name: 'Dmitri Volkov' })).toHaveAttribute('href', '/applications/app-9')
    // charts are described for assistive technology
    expect(await screen.findByRole('img', { name: /Applications by status/ })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Applications over time/ })).toBeInTheDocument()
  })

  it('re-queries the report when the period changes', async () => {
    signInAs('RECRUITER')
    const calls = handlers()
    const { user, router } = renderApp('/dashboard')
    await screen.findByRole('region', { name: 'Key figures' })
    await user.selectOptions(screen.getByLabelText('Reporting period'), '7')
    await waitFor(() => expect(calls.length).toBeGreaterThan(1))
    expect(router.state.location.search).toBe('?range=7')
    expect(calls[calls.length - 1]!.get('from_date')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('is scoped to assigned jobs for hiring managers', async () => {
    signInAs('HIRING_MANAGER')
    handlers({ ...DASH, scope: 'assigned_jobs' })
    renderApp('/dashboard')
    expect(await screen.findByText('Hiring activity for the jobs assigned to you.')).toBeInTheDocument()
  })

  it('shows helpful empty states when there is no activity', async () => {
    signInAs('RECRUITER')
    handlers(
      {
        ...DASH,
        kpis: {
          ...DASH.kpis,
          total_applications: 0,
          active_jobs: 0,
          shortlisted: 0,
          upcoming_interviews: 0,
          hires_in_period: 0,
        },
        funnel: [],
        applications_by_job: [],
        applications_over_time: [],
        status_distribution: [],
        recent_applications: [],
      },
      page([]),
    )
    renderApp('/dashboard')
    expect(await screen.findByText('No applications in this period')).toBeInTheDocument()
    expect(screen.getByText('No applicants yet')).toBeInTheDocument()
    expect(screen.getByText('No upcoming interviews')).toBeInTheDocument()
    expect(screen.getByText('No applications yet')).toBeInTheDocument()
  })

  it('surfaces a failed report with retry', async () => {
    signInAs('RECRUITER')
    let fail = true
    server.use(
      http.get('/api/v1/interviews', () => HttpResponse.json(INTERVIEWS)),
      http.get('/api/v1/reports/recruiter-dashboard', () =>
        fail ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 }) : HttpResponse.json(DASH),
      ),
    )
    const { user } = renderApp('/dashboard')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByRole('region', { name: 'Key figures' })).toBeInTheDocument()
    expect(await screen.findByRole('list', { name: 'Funnel stages' })).toBeInTheDocument()
  })
})
