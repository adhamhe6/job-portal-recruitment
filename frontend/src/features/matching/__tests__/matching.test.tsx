import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeCandidateView, makeMatched, makeMeta, JOB_ID } from '@/features/candidates/__tests__/testData'
import { errorBody, makeJobDetail, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { countActiveFilters, MATCHING_DEFAULTS, parseExplanation, toRankedFilters } from '../lib/matching'

describe('matching helpers', () => {
  it('converts the percentage filter to an API fraction and drops empty filters', () => {
    expect(
      toRankedFilters({ ...MATCHING_DEFAULTS, min_score: '65', applicants_only: 'true', page: 2 }),
    ).toEqual({
      min_score: 0.65,
      applicants_only: true,
      page: 2,
      page_size: 10,
    })
    expect(toRankedFilters(MATCHING_DEFAULTS)).toEqual({ page: 1, page_size: 10 })
    expect(countActiveFilters({ ...MATCHING_DEFAULTS, min_score: '10', availability: ['IMMEDIATELY'] })).toBe(
      2,
    )
  })

  it('reads the free-form explanation defensively', () => {
    const e = parseExplanation({
      skills: {
        required: {
          total: 2,
          matched: [{ name: 'Python' }],
          missing: ['Go'],
          related: [{ required: 'Go', candidate_has: 'Rust' }],
        },
      },
      weights: { required: 0.3, bad: 'x' },
      preferences: { location: 'Same city', odd: 5 },
    })
    expect(e.required?.matched).toEqual(['Python'])
    expect(e.required?.related).toEqual([{ required: 'Go', candidateHas: 'Rust' }])
    expect(e.preferred).toBeNull()
    expect(e.weights).toEqual({ required: 0.3 })
    expect(e.preferences).toEqual([{ label: 'Location', value: 'Same city' }])
    expect(parseExplanation(null).summary).toBeNull()
  })
})

const stats = (n: number) => ({
  job_id: JOB_ID,
  applications_total: 2,
  applications_by_status: {},
  matches_computed: n,
  last_matched_at: new Date(Date.now() - 7_200_000).toISOString(),
  extra: {},
})

function mockRanking(
  opts: { items?: ReturnType<typeof makeMatched>[]; meta?: ReturnType<typeof makeMeta>; total?: number } = {},
) {
  const calls: URLSearchParams[] = []
  const items = opts.items ?? [makeMatched()]
  server.use(
    http.get('/api/v1/jobs/:id', () =>
      HttpResponse.json(makeJobDetail({ id: JOB_ID, title: 'Machine Learning Engineer' })),
    ),
    http.get('/api/v1/matches/jobs/:jobId/candidates', ({ request }) => {
      calls.push(new URL(request.url).searchParams)
      return HttpResponse.json({
        ...page(items, { total: opts.total ?? items.length, page_size: 10, pages: 1 }),
        meta: opts.meta ?? makeMeta(),
      })
    }),
  )
  return calls
}
const last = (c: URLSearchParams[]) => c[c.length - 1]!

describe('matching: job picker (/matching)', () => {
  it('lists the company jobs with their match summary and links to the ranking', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/jobs', ({ request }) => {
        expect(new URL(request.url).searchParams.get('status')).toBe('PUBLISHED')
        return HttpResponse.json(page([makeJobListItem({ id: JOB_ID, title: 'Machine Learning Engineer' })]))
      }),
      http.get('/api/v1/jobs/:id/stats', () => HttpResponse.json(stats(16))),
    )
    renderApp('/matching')
    const link = await screen.findByRole('link', { name: 'Machine Learning Engineer' })
    expect(link).toHaveAttribute('href', `/matching/${JOB_ID}`)
    expect(await screen.findByText(/16 candidates scored/)).toBeInTheDocument()
    expect(screen.getByText(/2 applications/)).toBeInTheDocument()
    expect(screen.getByText(/Last updated/)).toBeInTheDocument()
    expect(screen.getByText('How to read match scores')).toBeInTheDocument()
  })

  it('shows an empty state with a way forward when there are no jobs', async () => {
    signInAs('RECRUITER')
    server.use(http.get('/api/v1/jobs', () => HttpResponse.json(page([]))))
    renderApp('/matching')
    expect(await screen.findByText('No published jobs yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Manage jobs' })).toHaveAttribute('href', '/manage/jobs')
  })

  it('shows a retryable error', async () => {
    signInAs('RECRUITER')
    let fail = true
    server.use(
      http.get('/api/v1/jobs', () =>
        fail
          ? HttpResponse.json(errorBody('X', 'boom'), { status: 500 })
          : HttpResponse.json(page([makeJobListItem()])),
      ),
      http.get('/api/v1/jobs/:id/stats', () => HttpResponse.json(stats(1))),
    )
    const { user } = renderApp('/matching')
    expect(await screen.findByText(/couldn't load your jobs/)).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByRole('link', { name: 'Senior Backend Engineer' })).toBeInTheDocument()
  })

  it('degrades to a note when a job’s summary cannot be loaded', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/jobs', () => HttpResponse.json(page([makeJobListItem({ id: JOB_ID })]))),
      http.get('/api/v1/jobs/:id/stats', () => HttpResponse.json(errorBody('X', 'boom'), { status: 500 })),
    )
    renderApp('/matching')
    expect(await screen.findByText('Match summary unavailable.')).toBeInTheDocument()
  })
})

describe('matching: ranking (/matching/:jobId)', () => {
  it('ranks candidates with score, summary, links and an expandable explanation', async () => {
    signInAs('RECRUITER')
    mockRanking({
      items: [
        makeMatched(),
        makeMatched({
          candidate_id: 'cand-2',
          display_name: 'Chen Wei',
          overall_percent: 55,
          band: 'GOOD',
          has_applied: false,
          application_id: null,
          application_status: null,
          stale: true,
        }),
      ],
    })
    const { user } = renderApp(`/matching/${JOB_ID}`)
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Candidates for Machine Learning Engineer' }),
    ).toBeInTheDocument()
    const first = (await screen.findByRole('heading', { name: 'Priya Nair' })).closest('article')!
    expect(within(first).getByText('79%')).toBeInTheDocument()
    expect(within(first).getByRole('link', { name: 'Priya Nair' })).toHaveAttribute(
      'href',
      `/candidates/cand-1?job_id=${JOB_ID}`,
    )
    expect(within(first).getByRole('link', { name: /View application/ })).toHaveAttribute(
      'href',
      '/applications/app-9',
    )
    expect(within(first).getByText('Screening')).toBeInTheDocument()
    expect(within(first).queryByText('Missing required skills')).not.toBeInTheDocument()

    await user.click(within(first).getByRole('button', { name: /Why this score/ }))
    expect(within(first).getByRole('meter', { name: 'Required skills' })).toHaveAttribute(
      'aria-valuenow',
      '75',
    )
    // a component that does not apply is "n/a", not 0%
    expect(within(first).getByRole('meter', { name: 'Preferred skills' })).toHaveAttribute(
      'aria-valuetext',
      'Not applicable for this job',
    )
    expect(within(first).getByText('Kubernetes')).toBeInTheDocument()
    expect(within(first).getByText('TensorFlow ≈ PyTorch')).toBeInTheDocument()
    expect(within(first).getByText('MLOps')).toBeInTheDocument()

    const second = screen.getByRole('heading', { name: 'Chen Wei' }).closest('article')!
    expect(within(second).getByText('Out of date')).toBeInTheDocument()
    expect(within(second).getByText('Has not applied')).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'Ranked candidates' })
    expect(within(list).getByText('#1')).toBeInTheDocument()
    expect(within(list).getByText('#2')).toBeInTheDocument()
    expect(
      screen.getAllByRole('link', { name: 'Applications' }).map((a) => a.getAttribute('href')),
    ).toContain(`/applications?job_id=${JOB_ID}`)
  })

  it('explains what the score does and does not mean', async () => {
    signInAs('RECRUITER')
    mockRanking()
    const { user } = renderApp(`/matching/${JOB_ID}`)
    await screen.findByText('Priya Nair')
    await user.click(screen.getByText('How to read match scores'))
    expect(screen.getByText(/ranking aid/)).toBeInTheDocument()
    expect(screen.getByText(/not a prediction of job performance or a hiring decision/)).toBeInTheDocument()
  })

  it('filters through the URL: minimum score as a fraction, applicants only, experience', async () => {
    signInAs('RECRUITER')
    const calls = mockRanking()
    const { user, router } = renderApp(
      `/matching/${JOB_ID}?min_score=60&applicants_only=true&availability=IMMEDIATELY&page=1`,
    )
    await screen.findByText('Priya Nair')
    expect(last(calls).get('min_score')).toBe('0.6')
    expect(last(calls).get('applicants_only')).toBe('true')
    expect(last(calls).getAll('availability')).toEqual(['IMMEDIATELY'])
    expect(screen.getByLabelText('Minimum score (%)')).toHaveValue(60)
    expect(screen.getByRole('checkbox', { name: /Only people who applied/ })).toBeChecked()
    await user.click(screen.getByRole('checkbox', { name: /Only people who applied/ }))
    await waitFor(() => expect(router.state.location.search).not.toContain('applicants_only'))
    await waitFor(() => expect(last(calls).has('applicants_only')).toBe(false))
  })

  it('shows a filtered-empty state and clears the filters', async () => {
    signInAs('RECRUITER')
    const calls = mockRanking({ items: [] })
    const { user, router } = renderApp(`/matching/${JOB_ID}?min_score=95`)
    expect(await screen.findByText('No candidates match these filters')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: /Clear/ })[0]!)
    await waitFor(() => expect(router.state.location.search).toBe(''))
    await waitFor(() => expect(last(calls).has('min_score')).toBe(false))
  })

  it('shows an empty state when nothing has been scored yet', async () => {
    signInAs('RECRUITER')
    mockRanking({ items: [], meta: makeMeta({ total_scored: 0, last_generated_at: null }) })
    renderApp(`/matching/${JOB_ID}`)
    expect(await screen.findByText('No candidates scored yet')).toBeInTheDocument()
    expect(screen.getByText('No matches have been computed for this job yet.')).toBeInTheDocument()
  })

  it('refreshes matches: queues the task, shows progress, then reloads the ranking', async () => {
    signInAs('RECRUITER')
    let generation = 0
    let taskPolls = 0
    let refreshBody = 0
    server.use(
      http.get('/api/v1/jobs/:id', () =>
        HttpResponse.json(makeJobDetail({ id: JOB_ID, title: 'Machine Learning Engineer' })),
      ),
      http.get('/api/v1/matches/jobs/:jobId/candidates', () =>
        HttpResponse.json({
          ...page([makeMatched({ display_name: generation === 0 ? 'Priya Nair' : 'Priya Nair (fresh)' })]),
          meta: makeMeta({ stale_rows: generation === 0 ? 3 : 0 }),
        }),
      ),
      http.post('/api/v1/matches/jobs/:jobId/refresh', () => {
        refreshBody++
        return HttpResponse.json({ task_id: 'task-7' }, { status: 202 })
      }),
      http.get('/api/v1/tasks/task-7', () => {
        taskPolls++
        if (taskPolls === 1)
          return HttpResponse.json({
            id: 'task-7',
            type: 'MATCH_JOB',
            status: 'RUNNING',
            progress: 40,
            stage: 'SCORING',
            result: null,
            error_code: null,
            error_message: null,
            attempts: 1,
            created_at: '',
            started_at: null,
            finished_at: null,
          })
        generation = 1
        return HttpResponse.json({
          id: 'task-7',
          type: 'MATCH_JOB',
          status: 'COMPLETED',
          progress: 100,
          stage: 'DONE',
          result: null,
          error_code: null,
          error_message: null,
          attempts: 1,
          created_at: '',
          started_at: null,
          finished_at: null,
        })
      }),
    )
    const { user } = renderApp(`/matching/${JOB_ID}`)
    expect(await screen.findByText('3 out of date')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Refresh matches' }))
    expect(await screen.findByRole('progressbar', { name: 'Match refresh progress' })).toBeInTheDocument()
    expect(screen.getByText('Scoring candidates…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Refreshing/ })).toBeDisabled()
    expect(await screen.findByText('Priya Nair (fresh)', undefined, { timeout: 8000 })).toBeInTheDocument()
    expect(refreshBody).toBe(1)
    await waitFor(() => expect(screen.queryByText('3 out of date')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Refresh matches' })).toBeEnabled()
  }, 15000)

  it('picks up a refresh the API already started (computing_task_id) and shows its progress', async () => {
    signInAs('RECRUITER')
    mockRanking({ meta: makeMeta({ computing_task_id: 'task-auto', stale_rows: 2 }) })
    server.use(
      http.get('/api/v1/tasks/task-auto', () =>
        HttpResponse.json({
          id: 'task-auto',
          type: 'MATCH_JOB',
          status: 'RUNNING',
          progress: 15,
          stage: 'LOADING',
          result: null,
          error_code: null,
          error_message: null,
          attempts: 1,
          created_at: '',
          started_at: null,
          finished_at: null,
        }),
      ),
    )
    renderApp(`/matching/${JOB_ID}`)
    expect(await screen.findByText('Loading candidates…')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Match refresh progress' })).toHaveAttribute(
      'aria-valuenow',
      '15',
    )
  })

  it('reports a failed refresh and allows trying again', async () => {
    signInAs('RECRUITER')
    mockRanking()
    server.use(
      http.post('/api/v1/matches/jobs/:jobId/refresh', () =>
        HttpResponse.json({ task_id: 'task-bad' }, { status: 202 }),
      ),
      http.get('/api/v1/tasks/task-bad', () =>
        HttpResponse.json({
          id: 'task-bad',
          type: 'MATCH_JOB',
          status: 'FAILED',
          progress: 20,
          stage: 'EMBEDDING',
          result: null,
          error_code: 'EMBEDDING_FAILED',
          error_message: 'The embedding model is unavailable.',
          attempts: 2,
          created_at: '',
          started_at: null,
          finished_at: null,
        }),
      ),
    )
    const { user } = renderApp(`/matching/${JOB_ID}`)
    await user.click(await screen.findByRole('button', { name: 'Refresh matches' }))
    expect(await screen.findByText('The match refresh failed')).toBeInTheDocument()
    expect(screen.getByText('The embedding model is unavailable.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('explains a rate-limited refresh', async () => {
    signInAs('RECRUITER')
    mockRanking()
    server.use(
      http.post('/api/v1/matches/jobs/:jobId/refresh', () =>
        HttpResponse.json(errorBody('RATE_LIMITED', 'x'), { status: 429 }),
      ),
    )
    const { user } = renderApp(`/matching/${JOB_ID}`)
    await user.click(await screen.findByRole('button', { name: 'Refresh matches' }))
    expect(await screen.findByText(/Too many refreshes/)).toBeInTheDocument()
  })

  it('hides the refresh action from staff who may only view matches (hiring manager)', async () => {
    signInAs('HIRING_MANAGER')
    mockRanking()
    renderApp(`/matching/${JOB_ID}`)
    await screen.findByText('Priya Nair')
    expect(screen.queryByRole('button', { name: /Refresh matches/ })).not.toBeInTheDocument()
    expect(screen.getByText(/last updated/)).toBeInTheDocument()
  })

  it('shows "job not found" for an unknown or foreign job (404)', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/jobs/:id', () =>
        HttpResponse.json(errorBody('JOB_NOT_FOUND', 'Job not found'), { status: 404 }),
      ),
      http.get('/api/v1/matches/jobs/:jobId/candidates', () =>
        HttpResponse.json(errorBody('JOB_NOT_FOUND', 'Job not found'), { status: 404 }),
      ),
    )
    renderApp('/matching/nope')
    expect(await screen.findByRole('heading', { name: 'Job not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to your jobs' })).toHaveAttribute('href', '/matching')
  })

  it('shows access denied on 403', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/jobs/:id', () => HttpResponse.json(errorBody('FORBIDDEN', 'no'), { status: 403 })),
      http.get('/api/v1/matches/jobs/:jobId/candidates', () =>
        HttpResponse.json(errorBody('FORBIDDEN', 'no'), { status: 403 }),
      ),
    )
    renderApp(`/matching/${JOB_ID}`)
    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
  })

  it('shows a retryable error when the ranking fails to load', async () => {
    signInAs('RECRUITER')
    let fail = true
    server.use(
      http.get('/api/v1/jobs/:id', () => HttpResponse.json(makeJobDetail({ id: JOB_ID, title: 'ML' }))),
      http.get('/api/v1/matches/jobs/:jobId/candidates', () =>
        fail
          ? HttpResponse.json(errorBody('X', 'boom'), { status: 500 })
          : HttpResponse.json({ ...page([makeMatched()]), meta: makeMeta() }),
      ),
    )
    const { user } = renderApp(`/matching/${JOB_ID}`)
    expect(await screen.findByText(/couldn't load the ranking/)).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByText('Priya Nair')).toBeInTheDocument()
  })

  it('links the candidate detail page back to the same job match', async () => {
    signInAs('RECRUITER')
    mockRanking()
    server.use(
      http.get('/api/v1/candidates/:id', () => HttpResponse.json(makeCandidateView())),
      http.get('/api/v1/jobs', () => HttpResponse.json(page([makeJobListItem({ id: JOB_ID })]))),
      http.get('/api/v1/matches/jobs/:jobId/candidates/:cid', () =>
        HttpResponse.json(
          { error: { code: 'MATCH_NOT_FOUND', message: 'x', details: null, request_id: 'r' } },
          { status: 404 },
        ),
      ),
    )
    const { user, router } = renderApp(`/matching/${JOB_ID}`)
    await user.click(await screen.findByRole('link', { name: 'Priya Nair' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/candidates/cand-1'))
    expect(router.state.location.search).toBe(`?job_id=${JOB_ID}`)
    expect(await screen.findByRole('heading', { level: 1, name: 'Priya Nair' })).toBeInTheDocument()
  })
})
