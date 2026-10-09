import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { staffTargets } from '../lib/workflow'
import { makeApplicationItem } from './fixtures'

const APPS = [
  makeApplicationItem({ id: 'a1', candidate_name: 'Ada Applied', status: 'APPLIED' }),
  makeApplicationItem({
    id: 'a2',
    candidate_name: 'Sam Screening',
    status: 'SCREENING',
    match_score: 0.4,
    match_band: 'PARTIAL',
  }),
  makeApplicationItem({ id: 'a3', candidate_name: 'Hana Hired', status: 'HIRED' }),
  makeApplicationItem({ id: 'a4', candidate_name: 'Rex Rejected', status: 'REJECTED' }),
]

function useList(items = APPS, overrides = {}) {
  const calls: URLSearchParams[] = []
  server.use(
    http.get('/api/v1/applications', ({ request }) => {
      calls.push(new URL(request.url).searchParams)
      return HttpResponse.json(page(items, overrides))
    }),
    http.get('/api/v1/jobs', () =>
      HttpResponse.json(page([makeJobListItem({ id: 'job-1', title: 'Senior Backend Engineer' })])),
    ),
  )
  return calls
}

const column = (name: string) => screen.getByRole('region', { name })
const last = (calls: URLSearchParams[]) => calls[calls.length - 1]!

describe('workflow rules (unit)', () => {
  it('offers only forward steps and rejection, never withdrawal', () => {
    expect(staffTargets('APPLIED')).toEqual(['SCREENING', 'REJECTED'])
    expect(staffTargets('OFFER')).toEqual(['HIRED', 'REJECTED'])
    expect(staffTargets('HIRED')).toEqual([])
    expect(staffTargets('WITHDRAWN')).toEqual([])
  })
  it('prefers the API-provided allowed targets', () => {
    expect(staffTargets('SCREENING', ['SHORTLISTED', 'WITHDRAWN'])).toEqual(['SHORTLISTED'])
  })
})

describe('applications pipeline (staff)', () => {
  it('groups applications into status columns and defaults to newest first', async () => {
    signInAs('RECRUITER')
    const calls = useList()
    renderApp('/applications')
    await screen.findByRole('link', { name: 'Ada Applied' })
    expect(within(column('Applied')).getByRole('link', { name: 'Ada Applied' })).toBeInTheDocument()
    expect(within(column('Screening')).getByRole('link', { name: 'Sam Screening' })).toBeInTheDocument()
    expect(within(column('Hired')).getByRole('link', { name: 'Hana Hired' })).toBeInTheDocument()
    expect(within(column('Rejected')).getByRole('link', { name: 'Rex Rejected' })).toBeInTheDocument()
    expect(within(column('Interview')).getByText('No applications')).toBeInTheDocument()
    expect(last(calls).get('sort')).toBe('newest')
    expect(last(calls).get('page_size')).toBe('100')
  })

  it('sends job, status, search and sort filters to the API and keeps them in the URL', async () => {
    signInAs('RECRUITER')
    const calls = useList()
    const { user, router } = renderApp('/applications?job_id=job-1')
    await screen.findByRole('link', { name: 'Ada Applied' })
    expect(last(calls).get('job_id')).toBe('job-1')
    expect(await screen.findByRole('list', { name: 'Active filters' })).toHaveTextContent(
      'Job: Senior Backend Engineer',
    )

    await user.type(screen.getByRole('searchbox', { name: 'Search applications' }), 'ada')
    await waitFor(() => expect(last(calls).get('q')).toBe('ada'), { timeout: 3000 })
    await user.selectOptions(screen.getByLabelText('Sort by'), 'match')
    await waitFor(() => expect(last(calls).get('sort')).toBe('match'))
    expect(router.state.location.search).toContain('sort=match')
  })

  it('filters by status through the select', async () => {
    signInAs('RECRUITER')
    const calls = useList()
    const { user } = renderApp('/applications')
    await screen.findByRole('link', { name: 'Ada Applied' })
    await user.click(screen.getByRole('combobox', { name: 'Filter by status' }))
    await user.click(await screen.findByRole('option', { name: 'Shortlisted' }))
    await waitFor(() => expect(last(calls).getAll('status')).toEqual(['SHORTLISTED']))
  })

  it('switches to the table view, sorts by match score and paginates', async () => {
    signInAs('RECRUITER')
    const calls = useList(APPS, { page: 1, pages: 3, total: 55, page_size: 20 })
    const { user, router } = renderApp('/applications?view=table')
    const table = await screen.findByRole('table')
    expect(within(table).getByRole('link', { name: 'Ada Applied' })).toBeInTheDocument()
    expect(last(calls).get('page_size')).toBe('20')

    await user.click(within(table).getByRole('button', { name: /match/i }))
    await waitFor(() => expect(last(calls).get('sort')).toBe('match'))

    await user.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => expect(last(calls).get('page')).toBe('2'))
    expect(router.state.location.search).toContain('page=2')
  })

  it('moves a card with the keyboard-accessible menu, optimistically, sending only valid targets', async () => {
    signInAs('RECRUITER')
    useList()
    let body: unknown
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    server.use(
      http.post('/api/v1/applications/a1/status', async ({ request }) => {
        body = await request.json()
        await gate
        return HttpResponse.json({ id: 'a1' })
      }),
    )
    const { user } = renderApp('/applications')
    await screen.findByRole('link', { name: 'Ada Applied' })
    await user.click(screen.getByRole('button', { name: 'Move Ada Applied' }))
    const menu = await screen.findByRole('menu')
    expect(
      within(menu)
        .getAllByRole('menuitem')
        .map((m) => m.textContent),
    ).toEqual([expect.stringContaining('Start screening'), expect.stringContaining('Reject')])
    await user.click(within(menu).getByRole('menuitem', { name: /Start screening/ }))
    // optimistic: the card is already in the Screening column while the request is pending
    await waitFor(() =>
      expect(within(column('Screening')).getByRole('link', { name: 'Ada Applied' })).toBeInTheDocument(),
    )
    expect(body).toEqual({ status: 'SCREENING', comment: null })
    release()
    expect(await screen.findByText('Ada Applied moved to Screening')).toBeInTheDocument()
  })

  it('rolls back and explains when the server refuses the move', async () => {
    signInAs('RECRUITER')
    useList()
    server.use(
      http.post('/api/v1/applications/a1/status', () =>
        HttpResponse.json(
          errorBody('INVALID_STATE_TRANSITION', 'nope', { from: 'APPLIED', to: 'SCREENING', allowed: [] }),
          { status: 409 },
        ),
      ),
    )
    const { user } = renderApp('/applications')
    await screen.findByRole('link', { name: 'Ada Applied' })
    await user.click(screen.getByRole('button', { name: 'Move Ada Applied' }))
    await user.click(await screen.findByRole('menuitem', { name: /Start screening/ }))
    expect(await screen.findByText("That move isn't possible")).toBeInTheDocument()
    expect(screen.getByText(/someone may have just changed it/i)).toBeInTheDocument()
    await waitFor(() =>
      expect(within(column('Applied')).getByRole('link', { name: 'Ada Applied' })).toBeInTheDocument(),
    )
  })

  it('asks for an optional reason when rejecting and sends it as the comment', async () => {
    signInAs('RECRUITER')
    useList()
    let body: unknown
    server.use(
      http.post('/api/v1/applications/a2/status', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ id: 'a2' })
      }),
    )
    const { user } = renderApp('/applications')
    await screen.findByRole('link', { name: 'Sam Screening' })
    await user.click(screen.getByRole('button', { name: 'Move Sam Screening' }))
    await user.click(await screen.findByRole('menuitem', { name: /Reject/ }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Reject Sam Screening?' })
    await user.type(within(dialog).getByLabelText(/Reason/), 'Missing Kafka experience')
    await user.click(within(dialog).getByRole('button', { name: 'Reject application' }))
    await waitFor(() => expect(body).toEqual({ status: 'REJECTED', comment: 'Missing Kafka experience' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  })

  it('offers no moves for finished applications', async () => {
    signInAs('RECRUITER')
    useList()
    const { user } = renderApp('/applications')
    await screen.findByRole('link', { name: 'Hana Hired' })
    await user.click(screen.getByRole('button', { name: 'Move Hana Hired' }))
    expect(await screen.findByRole('menuitem', { name: /No further moves/ })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
  })

  it('is read-only for hiring managers (no move controls)', async () => {
    signInAs('HIRING_MANAGER')
    useList()
    renderApp('/applications')
    await screen.findByRole('link', { name: 'Ada Applied' })
    expect(screen.queryByRole('button', { name: /^Move / })).not.toBeInTheDocument()
    expect(screen.queryByText(/Drag a card/)).not.toBeInTheDocument()
  })

  it('shows an empty state when there are no applications at all', async () => {
    signInAs('RECRUITER')
    useList([])
    renderApp('/applications')
    expect(await screen.findByRole('heading', { name: 'No applications yet' })).toBeInTheDocument()
  })

  it('shows a filtered-empty state with "Clear filters"', async () => {
    signInAs('RECRUITER')
    useList([])
    const { user, router } = renderApp('/applications?status=OFFER&q=zzz')
    expect(await screen.findByRole('heading', { name: 'No applications match' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).toBe(''))
  })

  it('surfaces load errors with retry', async () => {
    signInAs('RECRUITER')
    let fail = true
    server.use(
      http.get('/api/v1/jobs', () => HttpResponse.json(page([]))),
      http.get('/api/v1/applications', () =>
        fail
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 })
          : HttpResponse.json(page(APPS)),
      ),
    )
    const { user } = renderApp('/applications')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByRole('link', { name: 'Ada Applied' })).toBeInTheDocument()
  })
})
