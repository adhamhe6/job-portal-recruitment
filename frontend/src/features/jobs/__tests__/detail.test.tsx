import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, makeJobDetail, makeJobPublic } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const matchPayload = {
  overall_percent: 62,
  band: 'GOOD',
  summary: 'Good match; covers 2 of 3 required skills.',
  matched_skills: ['Python'],
  related_skills: [{ required: 'MySQL', candidate_has: 'PostgreSQL' }],
  missing_required: ['Kubernetes'],
  missing_preferred: ['Terraform'],
  experience_text: '5.5 years vs 4+ years required',
  experience_status: 'MEETS',
  semantic_band: 'HIGH',
  generated_at: new Date().toISOString(),
}

describe('job detail: visitors', () => {
  it('shows the public posting, required vs preferred skills and a sign-in call to action', async () => {
    server.use(http.get('/api/v1/jobs/:id', () => HttpResponse.json(makeJobPublic({ id: 'job-1' }))))
    renderApp('/jobs/job-1')
    expect(
      await screen.findByRole('heading', { level: 1, name: /Senior Backend Engineer/ }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'About the role' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Responsibilities' })).toBeInTheDocument()
    const required = screen.getByRole('heading', { name: 'Required' }).nextElementSibling as HTMLElement
    expect(within(required).getByText('Python')).toBeInTheDocument()
    expect(within(required).getByText('PostgreSQL · 3+ yrs')).toBeInTheDocument()
    const preferred = screen.getByRole('heading', { name: 'Nice to have' }).nextElementSibling as HTMLElement
    expect(within(preferred).getByText('Kubernetes')).toBeInTheDocument()
    expect(screen.getByText('€90,000 – €120,000')).toBeInTheDocument()
    // bullet list rendered from "- " lines
    expect(screen.getByText('Review code').closest('li')).toBeInTheDocument()
    const cta = screen.getByRole('link', { name: /sign in to apply/i })
    expect(cta).toHaveAttribute('href', `/login?next=${encodeURIComponent('/jobs/job-1')}`)
    // never any staff UI
    expect(screen.queryByText('Staff view')).not.toBeInTheDocument()
    expect(screen.queryByText('Applications by status')).not.toBeInTheDocument()
  })

  it('explains a missing/unavailable job instead of crashing', async () => {
    server.use(
      http.get('/api/v1/jobs/:id', () =>
        HttpResponse.json(errorBody('JOB_NOT_FOUND', 'Job not found'), { status: 404 }),
      ),
    )
    renderApp('/jobs/nope')
    expect(await screen.findByText('This job isn’t available')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Browse open jobs' })).toHaveAttribute('href', '/jobs')
  })
})

describe('job detail: candidates', () => {
  it('shows apply, save and the "How you match" explanation from real match data', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get('/api/v1/jobs/:id', () => HttpResponse.json(makeJobPublic({ id: 'job-1', is_saved: false }))),
      http.get('/api/v1/matches/me/jobs/:id', () => HttpResponse.json(matchPayload)),
    )
    renderApp('/jobs/job-1')
    expect(await screen.findByRole('button', { name: /apply now/i })).toBeEnabled()
    const card = (await screen.findByRole('heading', { name: /how you match/i })).closest(
      'div[class*="rounded-xl"]',
    ) as HTMLElement
    expect(within(card).getByText('62%')).toBeInTheDocument()
    expect(within(card).getByText('Good match')).toBeInTheDocument()
    expect(within(card).getByText('PostgreSQL ≈ MySQL')).toBeInTheDocument()
    expect(within(card).getByText('Kubernetes')).toBeInTheDocument()
    expect(within(card).getByText('5.5 years vs 4+ years required')).toBeInTheDocument()
    // skills the candidate has are marked in the posting itself
    expect(screen.getAllByLabelText('You have this skill').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Save Senior Backend Engineer' })).toBeInTheDocument()
  })

  it('hides the match card gracefully when no match exists (404)', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get('/api/v1/jobs/:id', () => HttpResponse.json(makeJobPublic({ id: 'job-1' }))),
      http.get('/api/v1/matches/me/jobs/:id', () =>
        HttpResponse.json(errorBody('MATCH_NOT_FOUND', 'No match yet'), { status: 404 }),
      ),
    )
    renderApp('/jobs/job-1')
    await screen.findByRole('button', { name: /apply now/i })
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: /how you match/i })).not.toBeInTheDocument(),
    )
    expect(screen.queryByText(/couldn't load your match/i)).not.toBeInTheDocument()
  })

  it('shows the application status instead of Apply when already applied', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get('/api/v1/jobs/:id', () =>
        HttpResponse.json(
          makeJobPublic({
            id: 'job-1',
            my_application_id: 'app-7',
            my_application_status: 'INTERVIEW',
            can_apply: false,
          }),
        ),
      ),
      http.get('/api/v1/matches/me/jobs/:id', () => HttpResponse.json(matchPayload)),
    )
    renderApp('/jobs/job-1')
    expect(await screen.findByText(/you applied · Interview/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View your application' })).toHaveAttribute(
      'href',
      '/applications/app-7',
    )
    expect(screen.queryByRole('button', { name: /apply now/i })).not.toBeInTheDocument()
  })

  it('disables Apply and says why when the job is closed to applications', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get('/api/v1/jobs/:id', () =>
        HttpResponse.json(
          makeJobPublic({
            id: 'job-1',
            can_apply: false,
            apply_blocked_reason: 'The application deadline has passed',
          }),
        ),
      ),
      http.get('/api/v1/matches/me/jobs/:id', () => HttpResponse.json(matchPayload)),
    )
    renderApp('/jobs/job-1')
    expect(await screen.findByRole('button', { name: /apply now/i })).toBeDisabled()
    expect(screen.getByText('The application deadline has passed')).toBeInTheDocument()
  })

  it('loads the job and the match in parallel (no request waterfall)', async () => {
    signInAs('CANDIDATE')
    let matchRequested: () => void = () => {}
    const matchSeen = new Promise<void>((r) => (matchRequested = r))
    server.use(
      http.get('/api/v1/jobs/:id', async () => {
        await matchSeen // the job response is held back until the match request has already started
        return HttpResponse.json(makeJobPublic({ id: 'job-1' }))
      }),
      http.get('/api/v1/matches/me/jobs/:id', () => {
        matchRequested()
        return HttpResponse.json(matchPayload)
      }),
    )
    renderApp('/jobs/job-1')
    expect(await screen.findByRole('button', { name: /apply now/i })).toBeInTheDocument()
  })
})

describe('job detail: staff of the owning company', () => {
  it('shows the staff representation with status, lifecycle actions, counts and the overview', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/jobs/:id', () =>
        HttpResponse.json(
          makeJobDetail({
            id: 'job-1',
            status: 'PUBLISHED',
            application_count: 7,
            allowed_transitions: ['CLOSED', 'PAUSED'],
            hiring_manager_name: 'Hannah Manager',
          }),
        ),
      ),
      http.get('/api/v1/jobs/:id/stats', () =>
        HttpResponse.json({
          job_id: 'job-1',
          applications_total: 7,
          applications_by_status: { APPLIED: 4, INTERVIEW: 3 },
          matches_computed: 16,
          last_matched_at: new Date().toISOString(),
          extra: {},
        }),
      ),
    )
    renderApp('/jobs/job-1')
    expect(await screen.findByText('Staff view')).toBeInTheDocument()
    expect(screen.getAllByText('Published').length).toBeGreaterThan(0)
    expect(screen.getByText('Hannah Manager')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Edit job' })).toHaveAttribute('href', '/manage/jobs/job-1/edit')
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Publish' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Applications \(7\)/ })).toHaveAttribute(
      'href',
      '/applications?job_id=job-1',
    )
    expect(
      within(screen.getByRole('main')).getByRole('link', { name: /candidate matching/i }),
    ).toHaveAttribute('href', '/matching/job-1')
    // overview from GET /jobs/:id/stats
    expect(await screen.findByRole('heading', { name: 'Applications by status' })).toBeInTheDocument()
    expect(await screen.findByText('16')).toBeInTheDocument()
    // staff never see the candidate apply UI
    expect(screen.queryByRole('button', { name: /apply now/i })).not.toBeInTheDocument()
  })

  it('drafts are viewable by staff, with publish and delete actions and a clear notice', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/jobs/:id', () =>
        HttpResponse.json(
          makeJobDetail({ id: 'job-1', status: 'DRAFT', allowed_transitions: ['ARCHIVED', 'PUBLISHED'] }),
        ),
      ),
      http.get('/api/v1/jobs/:id/stats', () =>
        HttpResponse.json({
          job_id: 'job-1',
          applications_total: 0,
          applications_by_status: {},
          matches_computed: 0,
          last_matched_at: null,
          extra: {},
        }),
      ),
    )
    renderApp('/jobs/job-1')
    expect(await screen.findByText(/not visible to candidates/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Archive' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /delete draft/i })).toBeInTheDocument()
  })

  it('hiring managers see the staff view but no management actions', async () => {
    signInAs('HIRING_MANAGER')
    server.use(
      http.get('/api/v1/jobs/:id', () =>
        HttpResponse.json(makeJobDetail({ id: 'job-1', allowed_transitions: [] })),
      ),
      http.get('/api/v1/jobs/:id/stats', () =>
        HttpResponse.json({
          job_id: 'job-1',
          applications_total: 3,
          applications_by_status: { APPLIED: 3 },
          matches_computed: 5,
          last_matched_at: null,
          extra: {},
        }),
      ),
    )
    renderApp('/jobs/job-1')
    expect(await screen.findByText('Staff view')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit job' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument()
    expect(
      within(screen.getByRole('main')).getByRole('link', { name: /candidate matching/i }),
    ).toBeInTheDocument()
  })
})
