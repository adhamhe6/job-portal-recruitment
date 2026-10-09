import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

/** Records the query string of every GET /search/jobs and answers with `items`. */
function captureSearch(
  items = [makeJobListItem({ id: 'job-1', title: 'Senior Backend Engineer' })],
  extra: Partial<ReturnType<typeof page>> = {},
) {
  const calls: URLSearchParams[] = []
  server.use(
    http.get('/api/v1/search/jobs', ({ request }) => {
      calls.push(new URL(request.url).searchParams)
      return HttpResponse.json(page(items, extra))
    }),
  )
  return calls
}
const last = (calls: URLSearchParams[]) => calls[calls.length - 1]!

describe('job search', () => {
  it('lists jobs with salary, skills, badges and a link to the detail page', async () => {
    captureSearch([
      makeJobListItem({
        id: 'job-9',
        title: 'Platform Engineer',
        company_name: 'Helio Health',
        skills: ['Docker', 'Terraform'],
        salary_min: '80000',
        salary_max: '105000',
        salary_currency: 'EUR',
        location: 'Munich, Germany',
        workplace_type: 'REMOTE',
      }),
    ])
    renderApp('/jobs')
    const card = (await screen.findByRole('heading', { name: 'Platform Engineer' })).closest('article')!
    expect(within(card).getByRole('link', { name: 'Platform Engineer' })).toHaveAttribute(
      'href',
      '/jobs/job-9',
    )
    expect(within(card).getByText('Helio Health')).toBeInTheDocument()
    expect(within(card).getByText('€80K – €105K')).toBeInTheDocument()
    expect(within(card).getByText('Munich, Germany')).toBeInTheDocument()
    expect(within(card).getByText('Remote')).toBeInTheDocument()
    expect(within(card).getByText('Terraform')).toBeInTheDocument()
    expect(await screen.findByText('1 job found')).toBeInTheDocument()
  })

  it('sends sensible defaults (newest first, page 1) when nothing is filtered', async () => {
    const calls = captureSearch()
    renderApp('/jobs')
    await screen.findByText('Senior Backend Engineer')
    expect(last(calls).get('sort')).toBe('newest')
    expect(last(calls).get('page')).toBe('1')
    expect(last(calls).get('page_size')).toBe('10')
    expect(last(calls).has('q')).toBe(false)
  })

  it('reads every filter from the URL and sends repeated params to the API (shareable links)', async () => {
    const calls = captureSearch()
    renderApp(
      '/jobs?q=platform&skill=Python&skill=SQL&skills_mode=all&location=Berlin&workplace_type=REMOTE&workplace_type=HYBRID&employment_type=FULL_TIME&experience_level=SENIOR&max_experience=5&salary_min=50000&salary_max=90000&posted_within_days=7&company_id=c-1&sort=salary_desc&page=2',
    )
    await screen.findByText('Senior Backend Engineer')
    const p = last(calls)
    expect(p.getAll('skill')).toEqual(['Python', 'SQL'])
    expect(p.get('skills_mode')).toBe('all')
    expect(p.get('q')).toBe('platform')
    expect(p.get('location')).toBe('Berlin')
    expect(p.getAll('workplace_type')).toEqual(['REMOTE', 'HYBRID'])
    expect(p.getAll('employment_type')).toEqual(['FULL_TIME'])
    expect(p.getAll('experience_level')).toEqual(['SENIOR'])
    expect(p.get('max_experience')).toBe('5')
    expect(p.get('salary_min')).toBe('50000')
    expect(p.get('salary_max')).toBe('90000')
    expect(p.get('posted_within_days')).toBe('7')
    expect(p.get('company_id')).toBe('c-1')
    expect(p.get('sort')).toBe('salary_desc')
    expect(p.get('page')).toBe('2')
    // the form reflects the URL
    expect(screen.getByRole('checkbox', { name: 'Remote' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Hybrid' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Senior' })).toBeChecked()
    expect(screen.getByLabelText('Minimum salary')).toHaveValue(50000)
  })

  it('toggling a checkbox writes the URL, resets to page 1 and refetches', async () => {
    const calls = captureSearch()
    const { user, router } = renderApp('/jobs?page=3')
    await screen.findByText('Senior Backend Engineer')
    await user.click(screen.getByRole('checkbox', { name: 'Remote' }))
    await waitFor(() => expect(router.state.location.search).toContain('workplace_type=REMOTE'))
    expect(router.state.location.search).not.toContain('page=')
    await waitFor(() => expect(last(calls).getAll('workplace_type')).toEqual(['REMOTE']))
    expect(last(calls).get('page')).toBe('1')
    // active filter chip + clear
    const chips = screen.getByRole('list', { name: 'Active filters' })
    await user.click(within(chips).getByRole('button', { name: 'Remove filter: Remote' }))
    await waitFor(() => expect(router.state.location.search).not.toContain('workplace_type'))
  })

  it('debounces the keyword box: one request after the user pauses, relevance sort kicks in', async () => {
    const calls = captureSearch()
    const { user, router } = renderApp('/jobs')
    await screen.findByText('Senior Backend Engineer')
    const before = calls.length
    await user.type(screen.getByRole('searchbox', { name: 'Search jobs' }), 'devops')
    await waitFor(() => expect(router.state.location.search).toContain('q=devops'), { timeout: 3000 })
    await waitFor(() => expect(last(calls).get('q')).toBe('devops'))
    expect(calls.length - before).toBe(1)
    expect(last(calls).get('sort')).toBe('relevance')
  })

  it('adds skills through the async picker (GET /skills?q=) and switches any/all', async () => {
    const calls = captureSearch()
    const skillQueries: string[] = []
    server.use(
      http.get('/api/v1/skills', ({ request }) => {
        skillQueries.push(new URL(request.url).searchParams.get('q') ?? '')
        return HttpResponse.json(
          page([{ id: 's-py', name: 'Python', category: 'Languages', family: null, is_verified: true }]),
        )
      }),
    )
    const { user, router } = renderApp('/jobs?skill=SQL')
    await screen.findByText('Senior Backend Engineer')
    await user.click(screen.getByRole('combobox', { name: 'Skills' }))
    await user.type(await screen.findByPlaceholderText('Type a skill name…'), 'pyth')
    await waitFor(() => expect(skillQueries).toContain('pyth')) // debounced autocomplete request
    await user.click(await screen.findByRole('option', { name: /Python/ }))
    await waitFor(() => expect(router.state.location.search).toContain('skill=SQL&skill=Python'))
    await waitFor(() => expect(last(calls).getAll('skill')).toEqual(['SQL', 'Python']))
    // with 2+ skills the any/all switch appears
    await user.click(await screen.findByRole('radio', { name: 'All of these' }))
    await waitFor(() => expect(last(calls).get('skills_mode')).toBe('all'))
    expect(router.state.location.search).toContain('skills_mode=all')
  })

  it('shows the empty state with a way out, and "Clear filters" resets the URL', async () => {
    server.use(http.get('/api/v1/search/jobs', () => HttpResponse.json(page([]))))
    const { user, router } = renderApp('/jobs?q=zzzz&workplace_type=ONSITE')
    expect(await screen.findByRole('heading', { name: 'No jobs found' })).toBeInTheDocument()
    expect(screen.getByText('Try changing your filters.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).toBe(''))
  })

  it('shows a retryable error state', async () => {
    let fail = true
    server.use(
      http.get('/api/v1/search/jobs', () =>
        fail
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(page([makeJobListItem({ title: 'Recovered Job' })])),
      ),
    )
    const { user } = renderApp('/jobs')
    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't load jobs/i)
    fail = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByText('Recovered Job')).toBeInTheDocument()
  })

  it('paginates through the URL', async () => {
    const calls = captureSearch([makeJobListItem({ title: 'Job on page one' })], { total: 25, pages: 3 })
    const { user, router } = renderApp('/jobs')
    await screen.findByText('Job on page one')
    await user.click(screen.getByRole('button', { name: 'Page 2' }))
    await waitFor(() => expect(router.state.location.search).toContain('page=2'))
    await waitFor(() => expect(last(calls).get('page')).toBe('2'))
  })

  it('anonymous visitors do not see match scores or the "Best match" sort', async () => {
    captureSearch([makeJobListItem({ match_score: 0.9 })])
    renderApp('/jobs')
    await screen.findByText('Senior Backend Engineer')
    expect(screen.queryByText('90%')).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Best match' })).not.toBeInTheDocument()
  })

  it('signed-in candidates get match percentages, applied badges and the "Best match" sort', async () => {
    signInAs('CANDIDATE')
    captureSearch([
      makeJobListItem({
        id: 'a',
        title: 'Matched Job',
        match_score: 0.82,
        has_applied: true,
        is_saved: false,
      }),
    ])
    renderApp('/jobs')
    const card = (await screen.findByRole('heading', { name: 'Matched Job' })).closest('article')!
    expect(within(card).getByText('82%')).toBeInTheDocument()
    expect(within(card).getByText('Applied')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Best match' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Saved' })).toHaveAttribute('href', '/jobs/saved')
  })
})
