import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeRecommendation, recommendationsPage } from '@/test/candidateFixtures'
import { errorBody } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const API = '/api/v1'
const taskBody = (over: Record<string, unknown> = {}) => ({
  id: 'task-9',
  type: 'REFRESH_EMBEDDINGS',
  status: 'RUNNING',
  progress: 30,
  stage: 'SCORING',
  result: null,
  error_code: null,
  error_message: null,
  attempts: 1,
  created_at: '2026-10-09T10:00:00Z',
  started_at: '2026-10-09T10:00:01Z',
  finished_at: null,
  ...over,
})

describe('RecommendedJobsPage', () => {
  afterEach(() => vi.useRealTimers())

  it('ranks recommendations with their match score and explains the match on demand', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/recommendations/jobs`, () =>
        HttpResponse.json(
          recommendationsPage([
            makeRecommendation({ id: 'j1', title: 'Platform Engineer' }, { overall_percent: 88 }),
            makeRecommendation(
              { id: 'j2', title: 'Backend Developer' },
              { overall_percent: 61, band: 'GOOD' },
            ),
          ]),
        ),
      ),
    )
    const { user } = renderApp('/recommended')
    expect(await screen.findByRole('heading', { level: 1, name: 'Recommended jobs' })).toBeInTheDocument()
    const list = await screen.findByRole('list', { name: 'Recommended jobs' })
    const first = within(list).getByRole('heading', { name: 'Platform Engineer' }).closest('li')!
    expect(within(first).getByText('88%')).toBeInTheDocument()
    expect(within(list).getByText('61%')).toBeInTheDocument()

    const why = within(first).getByRole('button', { name: /Why this match/ })
    expect(why).toHaveAttribute('aria-expanded', 'false')
    await user.click(why)
    expect(why).toHaveAttribute('aria-expanded', 'true')
    expect(within(first).getByText('Skills you have')).toBeInTheDocument()
    // 'Python' is on the job card and, once expanded, also in the matched-skills group
    expect(within(first).getAllByText('Python')).toHaveLength(2)
    expect(within(first).getByText('RabbitMQ ≈ Kafka')).toBeInTheDocument()
    expect(within(first).getByText('Kubernetes')).toBeInTheDocument()
    expect(within(first).getByText('Terraform')).toBeInTheDocument()
  })

  it('sends the filters from the URL to the API', async () => {
    signInAs('CANDIDATE')
    const seen: URLSearchParams[] = []
    server.use(
      http.get(`${API}/recommendations/jobs`, ({ request }) => {
        seen.push(new URL(request.url).searchParams)
        return HttpResponse.json(recommendationsPage([makeRecommendation()]))
      }),
    )
    renderApp(
      '/recommended?minScore=55&workplace=REMOTE&workplace=HYBRID&employment=FULL_TIME&location=Berlin&sort=newest',
    )
    await screen.findByRole('list', { name: 'Recommended jobs' })
    const p = seen[0]!
    expect(p.get('min_score')).toBe('0.55')
    expect(p.getAll('workplace_type')).toEqual(['REMOTE', 'HYBRID'])
    expect(p.getAll('employment_type')).toEqual(['FULL_TIME'])
    expect(p.get('location')).toBe('Berlin')
    expect(p.get('sort')).toBe('newest')
    const chips = screen.getByRole('list', { name: 'Active filters' })
    expect(within(chips).getByText('Match 55%+')).toBeInTheDocument()
    expect(within(chips).getByText('Location: Berlin')).toBeInTheDocument()
  })

  it('removing a filter chip updates the URL and the request', async () => {
    signInAs('CANDIDATE')
    const seen: URLSearchParams[] = []
    server.use(
      http.get(`${API}/recommendations/jobs`, ({ request }) => {
        seen.push(new URL(request.url).searchParams)
        return HttpResponse.json(recommendationsPage([makeRecommendation()]))
      }),
    )
    const { user, router } = renderApp('/recommended?minScore=75')
    await user.click(await screen.findByRole('button', { name: 'Remove filter: Match 75%+' }))
    await waitFor(() => expect(router.state.location.search).toBe(''))
    await waitFor(() => expect(seen.at(-1)?.has('min_score')).toBe(false))
  })

  it('queues a refresh, shows task progress, then reloads the list when it completes', async () => {
    signInAs('CANDIDATE')
    let listCalls = 0
    let taskCalls = 0
    server.use(
      http.get(`${API}/recommendations/jobs`, () => {
        listCalls++
        return HttpResponse.json(
          recommendationsPage([makeRecommendation({ title: listCalls > 1 ? 'Fresh Job' : 'Old Job' })]),
        )
      }),
      http.post(`${API}/recommendations/refresh`, () =>
        HttpResponse.json({ task_id: 'task-9', status: 'PENDING' }, { status: 202 }),
      ),
      http.get(`${API}/tasks/task-9`, () => {
        taskCalls++
        return HttpResponse.json(
          taskCalls === 1
            ? taskBody()
            : taskBody({
                status: 'COMPLETED',
                progress: 100,
                stage: 'DONE',
                finished_at: '2026-10-09T10:00:05Z',
              }),
        )
      }),
    )
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { user } = renderApp('/recommended')
    await screen.findByRole('heading', { name: 'Old Job' })
    await user.click(screen.getByRole('button', { name: /Refresh recommendations/ }))
    expect(
      await screen.findByRole('progressbar', { name: 'Recommendation refresh progress' }),
    ).toHaveAttribute('aria-valuenow', '30')
    expect(screen.getByText(/Scoring/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Refresh recommendations/ })).toBeDisabled()

    await vi.advanceTimersByTimeAsync(1600)
    expect(await screen.findByRole('heading', { name: 'Fresh Job' })).toBeInTheDocument()
    expect(await screen.findByText('Recommendations refreshed')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.queryByRole('progressbar', { name: 'Recommendation refresh progress' }),
      ).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /Refresh recommendations/ })).toBeEnabled()
  })

  it('shows a failed refresh and keeps the previous list', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/recommendations/jobs`, () =>
        HttpResponse.json(recommendationsPage([makeRecommendation({ title: 'Old Job' })])),
      ),
      http.post(`${API}/recommendations/refresh`, () =>
        HttpResponse.json({ task_id: 'task-9', status: 'PENDING' }, { status: 202 }),
      ),
      http.get(`${API}/tasks/task-9`, () =>
        HttpResponse.json(taskBody({ status: 'FAILED', error_message: 'Embedding service unavailable' })),
      ),
    )
    const { user } = renderApp('/recommended')
    await screen.findByRole('heading', { name: 'Old Job' })
    await user.click(screen.getByRole('button', { name: /Refresh recommendations/ }))
    expect(await screen.findByText('Refreshing your recommendations failed')).toBeInTheDocument()
    expect(screen.getByText(/Embedding service unavailable/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Old Job' })).toBeInTheDocument()
  })

  it('explains when refreshing is rate limited', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/recommendations/jobs`, () =>
        HttpResponse.json(recommendationsPage([makeRecommendation()])),
      ),
      http.post(`${API}/recommendations/refresh`, () =>
        HttpResponse.json(errorBody('RATE_LIMITED', 'Too many requests'), { status: 429 }),
      ),
    )
    const { user } = renderApp('/recommended')
    await user.click(await screen.findByRole('button', { name: /Refresh recommendations/ }))
    expect(await screen.findByText(/refreshed recently/)).toBeInTheDocument()
  })

  it('picks up a refresh that is already running on the server', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/recommendations/jobs`, () =>
        HttpResponse.json(recommendationsPage([], { computing: true, task_id: 'task-9' })),
      ),
      http.get(`${API}/tasks/task-9`, () => HttpResponse.json(taskBody({ progress: 65 }))),
    )
    renderApp('/recommended')
    const bar = await screen.findByRole('progressbar', { name: 'Recommendation refresh progress' })
    await waitFor(() => expect(bar).toHaveAttribute('aria-valuenow', '65'))
    expect(screen.getByRole('heading', { name: 'Working on your recommendations' })).toBeInTheDocument()
  })

  it('guides a candidate without a usable profile', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/recommendations/jobs`, () =>
        HttpResponse.json(
          recommendationsPage([], { profile_ready: false, hint: 'Add skills to get matches.' }),
        ),
      ),
    )
    renderApp('/recommended')
    expect(await screen.findByRole('heading', { name: 'No recommendations yet' })).toBeInTheDocument()
    expect(screen.getByText('Complete your profile for better recommendations')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Upload résumé' })).toHaveAttribute('href', '/resume')
  })

  it('shows a filter-aware empty state', async () => {
    signInAs('CANDIDATE')
    server.use(http.get(`${API}/recommendations/jobs`, () => HttpResponse.json(recommendationsPage([]))))
    const { user, router } = renderApp('/recommended?minScore=75')
    expect(
      await screen.findByRole('heading', { name: 'No recommendations match these filters' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).toBe(''))
  })

  it('shows an error state with retry', async () => {
    signInAs('CANDIDATE')
    let calls = 0
    server.use(
      http.get(`${API}/recommendations/jobs`, () => {
        calls++
        return calls === 1
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(recommendationsPage([makeRecommendation({ title: 'Recovered Job' })]))
      }),
    )
    const { user } = renderApp('/recommended')
    expect(
      await screen.findByRole('heading', { name: "We couldn't load your recommendations" }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByRole('heading', { name: 'Recovered Job' })).toBeInTheDocument()
  })
})
