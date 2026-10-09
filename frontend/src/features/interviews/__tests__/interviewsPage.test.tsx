import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { COMPANY_ID, errorBody, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { inHours, makeMember, makeStaffInterview, makeStaffView, RAVI } from './fixtures'

const API = '/api/v1'

const FUTURE = makeStaffInterview({
  id: 'iv-future',
  candidate_name: 'Nina Petrova',
  start_at: inHours(30),
  timezone: 'Europe/Berlin',
})
const STARTED = makeStaffInterview({
  id: 'iv-started',
  candidate_name: 'Alex Rivera',
  interview_type: 'PANEL',
  status: 'CONFIRMED',
  start_at: inHours(-0.5),
  meeting_url: null,
  location: 'HQ Room 3',
  feedback_count: 2,
  participants: [
    {
      user_id: 'user-recruiter',
      name: 'Riley Recruiter',
      role: 'INTERVIEWER',
      has_submitted_feedback: false,
    },
  ],
})

function mockApi(items = [STARTED, FUTURE]) {
  const calls: URLSearchParams[] = []
  server.use(
    http.get(`${API}/interviews`, ({ request }) => {
      calls.push(new URL(request.url).searchParams)
      return HttpResponse.json(page(items, { page_size: 50 }))
    }),
    http.get(`${API}/jobs`, () =>
      HttpResponse.json(page([makeJobListItem({ id: 'job-1', title: 'Senior Backend Engineer' })])),
    ),
    http.get(`${API}/companies/${COMPANY_ID}/members`, () =>
      HttpResponse.json([makeMember('user-ravi', 'Ravi'), makeMember('user-recruiter', 'Riley')]),
    ),
  )
  return calls
}
const last = (calls: URLSearchParams[]) => calls[calls.length - 1]!

describe('staff interviews page', () => {
  it('shows the agenda grouped by day with status, people and where', async () => {
    signInAs('RECRUITER')
    mockApi()
    renderApp('/interviews')
    const today = await screen.findByRole('heading', { name: /Today/ })
    expect(today).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Tomorrow|^[A-Z][a-z]{2}, / })).toBeInTheDocument()
    const alex = (await screen.findByRole('link', { name: /Alex Rivera/ })).closest('li')!
    expect(within(alex).getByText('Confirmed')).toBeInTheDocument()
    expect(within(alex).getByText('HQ Room 3')).toBeInTheDocument()
    expect(within(alex).getByText('2 feedback entries')).toBeInTheDocument()
    const nina = screen.getByRole('link', { name: /Nina Petrova/ }).closest('li')!
    expect(within(nina).getByText('Scheduled')).toBeInTheDocument()
    expect(within(nina).getByRole('link', { name: /Join link/ })).toHaveAttribute(
      'href',
      'https://meet.example.com/abc',
    )
    expect(within(nina).getByText(/Ravi Patel/)).toBeInTheDocument()
    expect(within(nina).getByText(/\(observer\)/)).toBeInTheDocument()
    // the zone is always named, never implicit
    expect(within(nina).getAllByText(/(UTC|GMT)/).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Schedule interview' })).toBeInTheDocument()
  })

  it('requests upcoming interviews by default and keeps every filter in the URL and the request', async () => {
    signInAs('RECRUITER')
    const calls = mockApi()
    const { user, router } = renderApp('/interviews')
    await screen.findByRole('link', { name: /Alex Rivera/ })
    expect(last(calls).get('upcoming_only')).toBe('true')
    expect(last(calls).get('sort')).toBe('start_asc')
    expect(last(calls).getAll('status')).toEqual([])

    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Confirmed' }))
    await waitFor(() => expect(last(calls).getAll('status')).toEqual(['CONFIRMED']))
    expect(router.state.location.search).toContain('status=CONFIRMED')
    await user.keyboard('{Escape}')

    await user.selectOptions(screen.getByLabelText('Job'), 'job-1')
    await waitFor(() => expect(last(calls).get('job_id')).toBe('job-1'))

    await user.type(screen.getByLabelText('From'), '2030-05-01')
    await waitFor(() => expect(last(calls).get('from_date')).toBe('2030-05-01'))
    await user.type(screen.getByLabelText('To'), '2030-05-31')
    await waitFor(() => expect(last(calls).get('to_date')).toBe('2030-05-31'))

    await user.click(screen.getByRole('checkbox', { name: 'Upcoming only' }))
    await waitFor(() => expect(last(calls).has('upcoming_only')).toBe(false))
    expect(router.state.location.search).toContain('upcoming=0')

    await user.selectOptions(screen.getByLabelText('Sort by'), 'start_desc')
    await waitFor(() => expect(last(calls).get('sort')).toBe('start_desc'))

    // active filters are removable chips; "Clear all" resets them
    expect(screen.getByRole('list', { name: 'Active filters' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear all' }))
    await waitFor(() => expect(last(calls).has('job_id')).toBe(false))
    expect(last(calls).has('from_date')).toBe(false)
    expect(last(calls).getAll('status')).toEqual([])
  })

  it('filters by interviewer on the client (the API has no such filter) over a full page', async () => {
    signInAs('RECRUITER')
    const calls = mockApi()
    const { user } = renderApp('/interviews')
    await screen.findByRole('link', { name: /Alex Rivera/ })
    await user.selectOptions(screen.getByLabelText('Interviewer'), RAVI.user_id)
    await waitFor(() => expect(screen.queryByRole('link', { name: /Alex Rivera/ })).not.toBeInTheDocument())
    expect(screen.getByRole('link', { name: /Nina Petrova/ })).toBeInTheDocument()
    expect(last(calls).get('page_size')).toBe('100')
  })

  it('warns about an invalid date range and does not call the API for it', async () => {
    signInAs('RECRUITER')
    const calls = mockApi()
    renderApp('/interviews?from=2030-06-01&to=2030-05-01')
    expect(await screen.findByText('Check the date range')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })

  it('has an empty state with next steps, and a "no match" state that clears filters', async () => {
    signInAs('RECRUITER')
    mockApi([])
    const first = renderApp('/interviews')
    expect(await screen.findByText('No upcoming interviews')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show past interviews' })).toBeInTheDocument()
    first.unmount()

    signInAs('RECRUITER')
    mockApi([])
    const { user, router } = renderApp('/interviews?job=job-1')
    expect(await screen.findByText('No interviews match')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).not.toContain('job='))
  })

  it('shows an error with retry', async () => {
    signInAs('RECRUITER')
    let fail = true
    server.use(
      http.get(`${API}/interviews`, () =>
        fail
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(page([FUTURE])),
      ),
      http.get(`${API}/jobs`, () => HttpResponse.json(page([]))),
      http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([])),
    )
    const { user } = renderApp('/interviews')
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByRole('link', { name: /Nina Petrova/ })).toBeInTheDocument()
  })

  it('switches to the list view', async () => {
    signInAs('RECRUITER')
    mockApi()
    const { user, router } = renderApp('/interviews')
    await screen.findByRole('link', { name: /Alex Rivera/ })
    await user.click(screen.getByRole('button', { name: /List/ }))
    await waitFor(() => expect(router.state.location.search).toContain('view=table'))
    const table = await screen.findByRole('table', { name: 'Interviews' })
    expect(within(table).getByRole('link', { name: 'Nina Petrova' })).toHaveAttribute(
      'href',
      `/interviews/${FUTURE.id}`,
    )
    expect(within(table).getByText('Panel interview')).toBeInTheDocument()
  })

  it('offers only the actions the state machine allows', async () => {
    signInAs('RECRUITER')
    mockApi()
    const { user } = renderApp('/interviews')
    await user.click(await screen.findByRole('button', { name: /Actions for interview with Nina Petrova/ }))
    let menu = await screen.findByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: 'Reschedule' })).toBeInTheDocument()
    expect(within(menu).getByRole('menuitem', { name: /Mark completed/ })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(within(menu).getByRole('menuitem', { name: /Record no-show/ })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(within(menu).getByRole('menuitem', { name: 'Cancel interview' })).toBeInTheDocument()
    await user.keyboard('{Escape}')

    await user.click(screen.getByRole('button', { name: /Actions for interview with Alex Rivera/ }))
    menu = await screen.findByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: /Mark completed/ })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    )
  })

  it('cancels with a required internal reason and refreshes the list', async () => {
    signInAs('RECRUITER')
    const calls = mockApi()
    let body: unknown = null
    server.use(
      http.post(`${API}/interviews/${FUTURE.id}/cancel`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(makeStaffView({ ...FUTURE, status: 'CANCELLED' }))
      }),
    )
    const { user } = renderApp('/interviews')
    await user.click(await screen.findByRole('button', { name: /Actions for interview with Nina Petrova/ }))
    await user.click(await screen.findByRole('menuitem', { name: 'Cancel interview' }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel interview' }))
    expect(await within(dialog).findByText(/at least 3 characters/)).toBeInTheDocument()
    expect(body).toBeNull()

    const before = calls.length
    await user.type(within(dialog).getByLabelText(/Reason/), 'Interviewer unavailable')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel interview' }))
    await waitFor(() => expect(body).toEqual({ reason: 'Interviewer unavailable' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    await waitFor(() => expect(calls.length).toBeGreaterThan(before))
  })

  it('keeps the dialog open and explains when an action is refused', async () => {
    signInAs('RECRUITER')
    mockApi()
    server.use(
      http.post(`${API}/interviews/${STARTED.id}/complete`, () =>
        HttpResponse.json(
          errorBody('INVALID_STATE_TRANSITION', 'A cancelled interview cannot be completed', {
            status: 'CANCELLED',
          }),
          { status: 409 },
        ),
      ),
    )
    const { user } = renderApp('/interviews')
    await user.click(await screen.findByRole('button', { name: /Actions for interview with Alex Rivera/ }))
    await user.click(await screen.findByRole('menuitem', { name: /Mark completed/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Mark completed' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      /cancelled interview cannot be completed/,
    )
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  })

  it('marks a started interview as completed', async () => {
    signInAs('RECRUITER')
    mockApi()
    let hit = false
    server.use(
      http.post(`${API}/interviews/${STARTED.id}/complete`, () => {
        hit = true
        return HttpResponse.json(makeStaffView({ ...STARTED, status: 'COMPLETED' }))
      }),
    )
    const { user } = renderApp('/interviews')
    await user.click(await screen.findByRole('button', { name: /Actions for interview with Alex Rivera/ }))
    await user.click(await screen.findByRole('menuitem', { name: /Mark completed/ }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Mark completed' }),
    )
    await waitFor(() => expect(hit).toBe(true))
  })

  it('hiring managers cannot schedule, reschedule or cancel', async () => {
    signInAs('HIRING_MANAGER')
    mockApi()
    const { user } = renderApp('/interviews')
    await screen.findByRole('link', { name: /Nina Petrova/ })
    expect(screen.queryByRole('button', { name: 'Schedule interview' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Actions for interview with Nina Petrova/ }))
    const menu = await screen.findByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: 'View details' })).toBeInTheDocument()
    expect(within(menu).queryByRole('menuitem', { name: 'Reschedule' })).not.toBeInTheDocument()
    expect(within(menu).queryByRole('menuitem', { name: 'Cancel interview' })).not.toBeInTheDocument()
  })
})
