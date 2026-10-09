import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, makeJobListItem, page, skill } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import {
  CANDIDATE_SEARCH_DEFAULTS,
  countActiveFilters,
  effectiveSort,
  experienceRangeError,
  toSearchQuery,
} from '../lib/filters'
import { makeCandidateItem } from './testData'

function captureSearch(items = [makeCandidateItem()], extra: Partial<ReturnType<typeof page>> = {}) {
  const calls: URLSearchParams[] = []
  server.use(
    http.get('/api/v1/search/candidates', ({ request }) => {
      calls.push(new URL(request.url).searchParams)
      return HttpResponse.json(page(items, extra))
    }),
    http.get('/api/v1/jobs', () =>
      HttpResponse.json(page([makeJobListItem({ id: 'job-live-1', title: 'Machine Learning Engineer' })])),
    ),
  )
  return calls
}
const last = (calls: URLSearchParams[]) => calls[calls.length - 1]!

describe('candidate filter helpers', () => {
  it('turns UI percentages into API fractions and ignores the match filters without a job', () => {
    const q = toSearchQuery({
      ...CANDIDATE_SEARCH_DEFAULTS,
      min_match_score: '60',
      job_id: 'j1',
      sort: 'match',
    })
    expect(q.min_match_score).toBeCloseTo(0.6)
    expect(q.sort).toBe('match')
    const noJob = toSearchQuery({ ...CANDIDATE_SEARCH_DEFAULTS, min_match_score: '60', sort: 'match' })
    expect(noJob.min_match_score).toBeUndefined()
    expect(noJob.sort).toBe('relevance')
    expect(effectiveSort({ ...CANDIDATE_SEARCH_DEFAULTS, sort: 'experience' })).toBe('experience')
  })

  it('does not send an impossible experience range and explains it', () => {
    const s = { ...CANDIDATE_SEARCH_DEFAULTS, min_experience: '8', max_experience: '3' }
    expect(experienceRangeError(s)).toMatch(/must not exceed/)
    expect(toSearchQuery(s).min_experience).toBeUndefined()
    expect(countActiveFilters(s)).toBe(1)
  })
})

describe('candidate search page', () => {
  it('lists candidates with skills, privacy badges and a link to the profile', async () => {
    signInAs('RECRUITER')
    captureSearch([
      makeCandidateItem({
        id: 'cand-7',
        display_name: 'Chen Wei',
        top_skills: ['Python', 'PyTorch'],
        skill_matches: ['Python'],
        has_applied: true,
        match_score: 0.82,
        match_band: 'STRONG',
      }),
      makeCandidateItem({
        id: 'cand-8',
        display_name: 'M A',
        headline: null,
        access: 'PROFILE',
        top_skills: [],
      }),
    ])
    renderApp('/candidates')
    const card = (await screen.findByRole('heading', { name: 'Chen Wei' })).closest('article')!
    expect(within(card).getByRole('link', { name: 'Chen Wei' })).toHaveAttribute('href', '/candidates/cand-7')
    expect(within(card).getByText('Applied to your jobs')).toBeInTheDocument()
    expect(within(card).getByText('PyTorch')).toBeInTheDocument()
    expect(within(card).getByText('82%')).toBeInTheDocument()
    expect(within(card).getByText('Within 2 weeks')).toBeInTheDocument()
    const marketplace = screen.getByRole('heading', { name: 'M A' }).closest('article')!
    expect(within(marketplace).getByText('Marketplace profile')).toBeInTheDocument()
    expect(within(marketplace).getByText('No skills listed.')).toBeInTheDocument()
    expect(await screen.findByText('2 candidates found')).toBeInTheDocument()
  })

  it('sends defaults: skills ALL, relevance sort, page size', async () => {
    signInAs('RECRUITER')
    const calls = captureSearch()
    renderApp('/candidates')
    await screen.findByText('Priya Nair')
    expect(last(calls).get('sort')).toBe('relevance')
    expect(last(calls).get('page')).toBe('1')
    expect(last(calls).get('page_size')).toBe('12')
    expect(last(calls).has('q')).toBe(false)
  })

  it('reads every filter from the URL, sends it to the API and reflects it in the form', async () => {
    signInAs('RECRUITER')
    const calls = captureSearch()
    renderApp(
      '/candidates?q=nlp&skill=Python&skill=SQL&skills_mode=any&min_experience=2&max_experience=8&location=Berlin&min_education=MASTER&certification=AWS&availability=IMMEDIATELY&availability=TWO_WEEKS&remote_preference=REMOTE&job_id=job-live-1&min_match_score=60&applicants_only=true&sort=match&page=2',
    )
    await screen.findByText('Priya Nair')
    const p = last(calls)
    expect(p.get('q')).toBe('nlp')
    expect(p.getAll('skill')).toEqual(['Python', 'SQL'])
    expect(p.get('skills_mode')).toBe('any')
    expect(p.get('min_experience')).toBe('2')
    expect(p.get('max_experience')).toBe('8')
    expect(p.get('location')).toBe('Berlin')
    expect(p.get('min_education')).toBe('MASTER')
    expect(p.get('certification')).toBe('AWS')
    expect(p.getAll('availability')).toEqual(['IMMEDIATELY', 'TWO_WEEKS'])
    expect(p.getAll('remote_preference')).toEqual(['REMOTE'])
    expect(p.get('job_id')).toBe('job-live-1')
    expect(p.get('min_match_score')).toBe('0.6')
    expect(p.get('applicants_only')).toBe('true')
    expect(p.get('sort')).toBe('match')
    expect(p.get('page')).toBe('2')
    expect(screen.getByRole('checkbox', { name: 'Immediately' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Remote' })).toBeChecked()
    expect(screen.getByLabelText('Minimum years of experience')).toHaveValue(2)
    expect(screen.getByRole('radio', { name: 'Any of these' })).toBeChecked()
    // links carry the job so the detail page can show the match
    expect(screen.getByRole('link', { name: 'Priya Nair' })).toHaveAttribute(
      'href',
      '/candidates/cand-1?job_id=job-live-1',
    )
  })

  it('debounces the keyword box and writes it to the URL', async () => {
    signInAs('RECRUITER')
    const calls = captureSearch()
    const { user, router } = renderApp('/candidates')
    await screen.findByText('Priya Nair')
    const before = calls.length
    await user.type(screen.getByRole('searchbox', { name: 'Search candidates' }), 'pytorch')
    await waitFor(() => expect(router.state.location.search).toContain('q=pytorch'), { timeout: 3000 })
    await waitFor(() => expect(last(calls).get('q')).toBe('pytorch'))
    expect(calls.length - before).toBe(1)
  })

  it('adds a skill through the autocomplete and removes it with its chip', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/skills', () => HttpResponse.json(page([skill('Python'), skill('PostgreSQL')]))),
    )
    const calls = captureSearch()
    const { user, router } = renderApp('/candidates')
    await screen.findByText('Priya Nair')
    await user.click(screen.getByRole('combobox', { name: /skills/i }))
    await user.click(await screen.findByRole('option', { name: /PostgreSQL/ }))
    await waitFor(() => expect(router.state.location.search).toContain('skill=PostgreSQL'))
    await waitFor(() => expect(last(calls).getAll('skill')).toEqual(['PostgreSQL']))
    const chips = screen.getByRole('list', { name: 'Active filters' })
    await user.click(within(chips).getByRole('button', { name: 'Remove filter: PostgreSQL' }))
    await waitFor(() => expect(router.state.location.search).not.toContain('skill='))
  })

  it('shows a validation message and holds back the request for min > max experience', async () => {
    signInAs('RECRUITER')
    const calls = captureSearch()
    renderApp('/candidates?min_experience=9&max_experience=2')
    await screen.findByText('Priya Nair')
    expect(screen.getByText('Minimum experience must not exceed the maximum.')).toBeInTheDocument()
    expect(last(calls).has('min_experience')).toBe(false)
  })

  it('paginates through the URL', async () => {
    signInAs('RECRUITER')
    const calls = captureSearch([makeCandidateItem()], { total: 30, pages: 3, page_size: 12 })
    const { user, router } = renderApp('/candidates')
    await screen.findByText('Priya Nair')
    await user.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => expect(router.state.location.search).toContain('page=2'))
    await waitFor(() => expect(last(calls).get('page')).toBe('2'))
  })

  it('explains an empty result and clears the filters', async () => {
    signInAs('RECRUITER')
    const calls = captureSearch([])
    const { user, router } = renderApp('/candidates?location=Atlantis')
    expect(await screen.findByText('No candidates found')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).toBe(''))
    await waitFor(() => expect(last(calls).has('location')).toBe(false))
  })

  it('shows a first-use empty state when the company has no candidates yet', async () => {
    signInAs('RECRUITER')
    captureSearch([])
    renderApp('/candidates')
    expect(await screen.findByText('No candidates yet')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Bulk résumé import/ }).length).toBeGreaterThan(0)
  })

  it('shows a retryable error', async () => {
    signInAs('RECRUITER')
    let fail = true
    server.use(
      http.get('/api/v1/search/candidates', () =>
        fail
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(page([makeCandidateItem()])),
      ),
      http.get('/api/v1/jobs', () => HttpResponse.json(page([]))),
    )
    const { user } = renderApp('/candidates')
    expect(await screen.findByText(/couldn't search candidates/)).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByText('Priya Nair')).toBeInTheDocument()
  })

  it('tells a hiring manager that search is not available instead of calling the API', async () => {
    signInAs('HIRING_MANAGER')
    let called = false
    server.use(
      http.get('/api/v1/search/candidates', () => {
        called = true
        return HttpResponse.json(page([]))
      }),
    )
    renderApp('/candidates')
    expect(await screen.findByText(/Candidate search isn’t available for your role/)).toBeInTheDocument()
    expect(called).toBe(false)
  })

  it('hides the bulk import entry from staff without the import permission', async () => {
    signInAs('RECRUITER', { permissions: ['search_candidates', 'view_candidates', 'view_company_jobs'] })
    captureSearch()
    renderApp('/candidates')
    await screen.findByText('Priya Nair')
    expect(screen.queryByRole('button', { name: /Bulk résumé import/ })).not.toBeInTheDocument()
  })
})
