import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { availableActions, JOB_TRANSITIONS } from '../lib/lifecycle'
import { errorBody, makeJobDetail, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const JOBS = [
  makeJobListItem({ id: 'draft-1', title: 'Draft Role', status: 'DRAFT', published_at: null, application_count: 0 }),
  makeJobListItem({ id: 'live-1', title: 'Live Role', status: 'PUBLISHED', application_count: 4 }),
  makeJobListItem({ id: 'paused-1', title: 'Paused Role', status: 'PAUSED', application_count: 1 }),
  makeJobListItem({ id: 'closed-1', title: 'Closed Role', status: 'CLOSED', application_count: 2 }),
]

function listHandler() {
  const calls: URLSearchParams[] = []
  server.use(
    http.get('/api/v1/jobs', ({ request }) => {
      calls.push(new URL(request.url).searchParams)
      return HttpResponse.json(page(JOBS))
    }),
  )
  return calls
}

const openMenu = async (user: ReturnType<typeof renderApp>['user'], title: string) => {
  await user.click(await screen.findByRole('button', { name: `Actions for ${title}` }))
  return screen.findByRole('menu')
}

describe('lifecycle rules (unit)', () => {
  it('offers exactly the transitions the backend state machine allows', () => {
    expect(availableActions('DRAFT')).toEqual(['publish', 'archive'])
    expect(availableActions('PUBLISHED')).toEqual(['pause', 'close'])
    expect(availableActions('PAUSED')).toEqual(['resume', 'close'])
    expect(availableActions('CLOSED')).toEqual(['archive'])
    expect(availableActions('ARCHIVED')).toEqual([])
  })
  it('prefers the API-provided allowed_transitions', () => {
    expect(availableActions('PUBLISHED', ['CLOSED'])).toEqual(['close'])
    expect(availableActions('DRAFT', [])).toEqual([])
    expect(Object.keys(JOB_TRANSITIONS)).toHaveLength(5)
  })
})

describe('jobs management list', () => {
  it('lists the company jobs with status, applications and per-status filtering via the URL', async () => {
    signInAs('RECRUITER')
    const calls = listHandler()
    const { user, router } = renderApp('/manage/jobs')
    const row = (await screen.findByRole('link', { name: 'Live Role' })).closest('tr')!
    expect(within(row).getByText('Published')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: /4 applications for Live Role/ })).toHaveAttribute('href', '/applications?job_id=live-1')
    expect(calls[calls.length - 1]!.has('status')).toBe(false)
    expect(calls[calls.length - 1]!.get('sort')).toBe('newest')

    await user.click(screen.getByRole('tab', { name: 'Draft' }))
    await waitFor(() => expect(router.state.location.search).toContain('status=DRAFT'))
    await waitFor(() => expect(calls[calls.length - 1]!.getAll('status')).toEqual(['DRAFT']))
  })

  it('searches and sorts server-side', async () => {
    signInAs('RECRUITER')
    const calls = listHandler()
    const { user } = renderApp('/manage/jobs')
    await screen.findByRole('link', { name: 'Live Role' })
    await user.type(screen.getByRole('searchbox', { name: 'Search jobs' }), 'engineer')
    await waitFor(() => expect(calls[calls.length - 1]!.get('q')).toBe('engineer'), { timeout: 3000 })
    await user.selectOptions(screen.getByLabelText('Sort by'), 'title')
    await waitFor(() => expect(calls[calls.length - 1]!.get('sort')).toBe('title'))
  })

  it('shows an empty state with a next action for a company without jobs', async () => {
    signInAs('RECRUITER')
    server.use(http.get('/api/v1/jobs', () => HttpResponse.json(page([]))))
    renderApp('/manage/jobs')
    expect(await screen.findByRole('heading', { name: 'No jobs yet' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /create a job|new job/i })[0]).toHaveAttribute('href', '/manage/jobs/new')
  })

  it('shows a filtered-empty state with "Clear filters"', async () => {
    signInAs('RECRUITER')
    server.use(http.get('/api/v1/jobs', () => HttpResponse.json(page([]))))
    const { user, router } = renderApp('/manage/jobs?status=ARCHIVED&q=nothing')
    expect(await screen.findByRole('heading', { name: 'No jobs match' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).toBe(''))
  })

  it('surfaces load errors with retry', async () => {
    signInAs('RECRUITER')
    let fail = true
    server.use(http.get('/api/v1/jobs', () => (fail ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 }) : HttpResponse.json(page(JOBS)))))
    const { user } = renderApp('/manage/jobs')
    expect(await screen.findByRole('alert')).toHaveTextContent(/service unavailable/i)
    fail = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByRole('link', { name: 'Live Role' })).toBeInTheDocument()
  })

  it('offers only the actions that fit each status', async () => {
    signInAs('RECRUITER')
    listHandler()
    const { user } = renderApp('/manage/jobs')
    let menu = await openMenu(user, 'Draft Role')
    expect(within(menu).getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['View job', 'Edit', 'Applications', 'Candidate matching', 'Publish', 'Archive', 'Delete draft'])
    await user.keyboard('{Escape}')
    menu = await openMenu(user, 'Paused Role')
    expect(within(menu).getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['View job', 'Edit', 'Applications', 'Candidate matching', 'Resume', 'Close'])
    await user.keyboard('{Escape}')
    menu = await openMenu(user, 'Closed Role')
    expect(within(menu).queryByRole('menuitem', { name: 'Edit' })).not.toBeInTheDocument() // closed jobs are read-only
    expect(within(menu).getByRole('menuitem', { name: 'Archive' })).toBeInTheDocument()
  })

  it('hiring managers can view but not manage', async () => {
    signInAs('HIRING_MANAGER')
    listHandler()
    const { user } = renderApp('/manage/jobs')
    const menu = await openMenu(user, 'Live Role')
    expect(within(menu).getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['View job', 'Applications', 'Candidate matching'])
    expect(screen.queryByRole('link', { name: /new job/i })).not.toBeInTheDocument()
  })
})

describe('lifecycle actions with confirmation', () => {
  it('publish asks first, then POSTs /publish and refreshes the list', async () => {
    signInAs('RECRUITER')
    const calls = listHandler()
    let published = ''
    server.use(
      http.post('/api/v1/jobs/:id/publish', ({ params }) => {
        published = String(params.id)
        return HttpResponse.json(makeJobDetail({ id: 'draft-1', status: 'PUBLISHED' }))
      }),
    )
    const { user } = renderApp('/manage/jobs')
    const menu = await openMenu(user, 'Draft Role')
    await user.click(within(menu).getByRole('menuitem', { name: 'Publish' }))
    const dialog = await screen.findByRole('alertdialog', { name: /publish “Draft Role”\?/i })
    expect(published).toBe('') // nothing happens before confirming
    const before = calls.length
    await user.click(within(dialog).getByRole('button', { name: 'Publish job' }))
    await waitFor(() => expect(published).toBe('draft-1'))
    expect(await screen.findByText('Job published')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    await waitFor(() => expect(calls.length).toBeGreaterThan(before)) // list invalidated and refetched
  })

  it('cancel closes the dialog without calling the API', async () => {
    signInAs('RECRUITER')
    listHandler()
    let called = false
    server.use(http.post('/api/v1/jobs/:id/close', () => ((called = true), HttpResponse.json(makeJobDetail()))))
    const { user } = renderApp('/manage/jobs')
    const menu = await openMenu(user, 'Live Role')
    await user.click(within(menu).getByRole('menuitem', { name: 'Close' }))
    const dialog = await screen.findByRole('alertdialog', { name: /close “Live Role”\?/i })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(called).toBe(false)
  })

  it('pause sends the optional reason', async () => {
    signInAs('RECRUITER')
    listHandler()
    let body: unknown
    server.use(
      http.post('/api/v1/jobs/:id/pause', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(makeJobDetail({ id: 'live-1', status: 'PAUSED' }))
      }),
    )
    const { user } = renderApp('/manage/jobs')
    const menu = await openMenu(user, 'Live Role')
    await user.click(within(menu).getByRole('menuitem', { name: 'Pause' }))
    const dialog = await screen.findByRole('alertdialog')
    await user.type(within(dialog).getByLabelText(/reason/i), 'Hiring freeze')
    await user.click(within(dialog).getByRole('button', { name: 'Pause job' }))
    await waitFor(() => expect(body).toEqual({ reason: 'Hiring freeze' }))
  })

  it('deleting a draft is a destructive confirmation and calls DELETE', async () => {
    signInAs('RECRUITER')
    listHandler()
    let deleted = ''
    server.use(
      http.delete('/api/v1/jobs/:id', ({ params }) => {
        deleted = String(params.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { user } = renderApp('/manage/jobs')
    const menu = await openMenu(user, 'Draft Role')
    await user.click(within(menu).getByRole('menuitem', { name: 'Delete draft' }))
    const dialog = await screen.findByRole('alertdialog', { name: /delete draft “Draft Role”\?/i })
    expect(within(dialog).getByText(/cannot be undone/i)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Delete draft' }))
    await waitFor(() => expect(deleted).toBe('draft-1'))
    expect(await screen.findByText('Draft deleted')).toBeInTheDocument()
  })

  it('explains INVALID_STATE_TRANSITION in plain language and keeps the dialog open', async () => {
    signInAs('RECRUITER')
    listHandler()
    server.use(
      http.post('/api/v1/jobs/:id/pause', () =>
        HttpResponse.json(errorBody('INVALID_STATE_TRANSITION', 'A closed job cannot become paused', { from: 'CLOSED', to: 'PAUSED', allowed: ['ARCHIVED'] }), { status: 409 }),
      ),
    )
    const { user } = renderApp('/manage/jobs')
    const menu = await openMenu(user, 'Live Role')
    await user.click(within(menu).getByRole('menuitem', { name: 'Pause' }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Pause job' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent("That change isn't possible right now")
    expect(alert).toHaveTextContent("This job is currently closed, so it can't become paused")
  })

  it('lists every reason when publishing fails (PUBLISH_VALIDATION_FAILED) and links to the editor', async () => {
    signInAs('RECRUITER')
    listHandler()
    server.use(
      http.post('/api/v1/jobs/:id/publish', () =>
        HttpResponse.json(errorBody('PUBLISH_VALIDATION_FAILED', 'This job cannot be published yet', ['Description must be at least 30 characters', 'Add at least one required skill']), { status: 422 }),
      ),
    )
    const { user } = renderApp('/manage/jobs')
    const menu = await openMenu(user, 'Draft Role')
    await user.click(within(menu).getByRole('menuitem', { name: 'Publish' }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Publish job' }))
    expect(await within(dialog).findByText("This job can't be published yet")).toBeInTheDocument()
    expect(within(dialog).getByText('Description must be at least 30 characters')).toBeInTheDocument()
    expect(within(dialog).getByText('Add at least one required skill')).toBeInTheDocument()
    expect(within(dialog).getByRole('link', { name: 'Edit this job' })).toHaveAttribute('href', '/manage/jobs/draft-1/edit')
  })

  it('works from the job detail page too (close -> status updates in place)', async () => {
    signInAs('RECRUITER')
    let status: 'PUBLISHED' | 'CLOSED' = 'PUBLISHED'
    server.use(
      http.get('/api/v1/jobs/job-1', () => HttpResponse.json(makeJobDetail({ id: 'job-1', status, allowed_transitions: status === 'PUBLISHED' ? ['CLOSED', 'PAUSED'] : ['ARCHIVED'] }))),
      http.get('/api/v1/jobs/job-1/stats', () => HttpResponse.json({ job_id: 'job-1', applications_total: 0, applications_by_status: {}, matches_computed: 0, last_matched_at: null, extra: {} })),
      http.post('/api/v1/jobs/job-1/close', () => {
        status = 'CLOSED'
        return HttpResponse.json(makeJobDetail({ id: 'job-1', status, allowed_transitions: ['ARCHIVED'] }))
      }),
    )
    const { user } = renderApp('/jobs/job-1')
    await user.click(await screen.findByRole('button', { name: 'Close' }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Close job' }))
    expect(await screen.findByRole('button', { name: 'Archive' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit job' })).not.toBeInTheDocument() // closed => read-only
  })
})
