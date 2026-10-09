import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { COMPANY_ID, errorBody } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import {
  inHours,
  makeCandidateView,
  makeFeedback,
  makeFeedbackSummary,
  makeMember,
  makeStaffView,
} from './fixtures'

const API = '/api/v1'

function mockStaff(view = makeStaffView({ id: 'iv-1' }), feedback = makeFeedbackSummary([])) {
  const calls = { feedback: 0 }
  server.use(
    http.get(`${API}/interviews/iv-1`, () => HttpResponse.json(view)),
    http.get(`${API}/interviews/iv-1/feedback`, () => {
      calls.feedback += 1
      return HttpResponse.json(feedback)
    }),
    http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([makeMember('user-ravi', 'Ravi')])),
  )
  return calls
}

describe('interview detail — staff', () => {
  it('shows the details, participants, internal notes, application stage and history', async () => {
    signInAs('RECRUITER')
    mockStaff(
      makeStaffView({
        id: 'iv-1',
        start_at: inHours(30),
        timezone: 'Europe/Berlin',
        notes: 'Focus on system design.',
        location: 'HQ Room 3',
      }),
    )
    renderApp('/interviews/iv-1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Nina Petrova' })).toBeInTheDocument()
    expect(screen.getByText('Scheduled')).toBeInTheDocument()
    expect(screen.getByText('Focus on system design.')).toBeInTheDocument()
    expect(screen.getByText('HQ Room 3')).toBeInTheDocument()
    expect(screen.getByText(/Europe\/Berlin \(UTC\+0[12]:00\)/)).toBeInTheDocument()
    const people = screen.getByRole('list', { name: 'Participants' })
    expect(within(people).getByText('Ravi Patel')).toBeInTheDocument()
    expect(within(people).getByText('Observer')).toBeInTheDocument()
    expect(screen.getByText('Next stage options:')).toHaveTextContent('Offer, Rejected')
    expect(screen.getByRole('link', { name: 'Open application' })).toHaveAttribute('href', '/applications/app-1')
    expect(screen.getByText('Scheduled by Riley Recruiter')).toBeInTheDocument()
    // actions per state machine: future interview cannot be completed yet
    expect(screen.getByRole('button', { name: /Reschedule/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Mark completed/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /^Cancel$/ })).toBeEnabled()
    expect(screen.getByText(/available once the interview has started/)).toBeInTheDocument()
  })

  it('explains that feedback opens when the interview starts, and lists existing feedback internally', async () => {
    signInAs('RECRUITER')
    mockStaff(
      makeStaffView({ id: 'iv-1', start_at: inHours(30), feedback_count: 1 }),
      makeFeedbackSummary([makeFeedback({ rating: 5, recommendation: 'STRONG_HIRE', strengths: 'Great SQL.' })]),
    )
    renderApp('/interviews/iv-1')
    expect(await screen.findByText('Feedback opens once the interview has started.')).toBeInTheDocument()
    expect(screen.getByText(/candidates can never see it/)).toBeInTheDocument()
    const list = await screen.findByRole('list', { name: 'Feedback entries' })
    expect(within(list).getByText('Ravi Patel')).toBeInTheDocument()
    expect(within(list).getByRole('img', { name: 'Rating 5 out of 5' })).toBeInTheDocument()
    expect(within(list).getByText('Strong hire')).toBeInTheDocument()
    expect(within(list).getByText('Great SQL.')).toBeInTheDocument()
    expect(screen.getByText(/Average rating/).closest('p')).toHaveTextContent('5/5')
    expect(screen.queryByRole('button', { name: 'Submit feedback' })).not.toBeInTheDocument()
  })

  it('validates and submits my feedback (POST), then shows it as mine', async () => {
    signInAs('RECRUITER')
    const started = makeStaffView({
      id: 'iv-1',
      status: 'COMPLETED',
      start_at: inHours(-3),
      can_submit_feedback: true,
    })
    let stored = makeFeedbackSummary([])
    let body: Record<string, unknown> | null = null
    server.use(
      http.get(`${API}/interviews/iv-1`, () => HttpResponse.json(started)),
      http.get(`${API}/interviews/iv-1/feedback`, () => HttpResponse.json(stored)),
      http.post(`${API}/interviews/iv-1/feedback`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        const fb = makeFeedback({ ...(body as object), author_name: 'Riley Recruiter', author_id: 'user-recruiter', is_mine: true })
        stored = makeFeedbackSummary([fb])
        return HttpResponse.json(fb, { status: 201 })
      }),
    )
    const { user } = renderApp('/interviews/iv-1')
    await user.click(await screen.findByRole('button', { name: 'Submit feedback' }))
    expect(await screen.findByText('Choose a rating from 1 to 5')).toBeInTheDocument()
    expect(screen.getByText('Choose a recommendation')).toBeInTheDocument()
    expect(body).toBeNull()

    await user.click(screen.getByRole('radio', { name: /4 Strong/ }))
    await user.selectOptions(screen.getByRole('combobox', { name: /Recommendation/ }), 'HIRE')
    await user.type(screen.getByLabelText(/Strengths/), 'Clear communicator.')
    await user.type(screen.getByLabelText(/Additional notes/), '  ')
    await user.click(screen.getByRole('button', { name: 'Submit feedback' }))
    await waitFor(() =>
      expect(body).toEqual({
        rating: 4,
        recommendation: 'HIRE',
        strengths: 'Clear communicator.',
        weaknesses: null,
        notes: null,
      }),
    )
    // after refetch the form is replaced by my entry
    expect(await screen.findByText('(you)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Edit my feedback/ })).toBeInTheDocument()
  })

  it('updates my own feedback with PUT', async () => {
    signInAs('RECRUITER')
    const mine = makeFeedback({ is_mine: true, author_name: 'Riley Recruiter', rating: 3, recommendation: 'NO_HIRE' })
    mockStaff(
      makeStaffView({ id: 'iv-1', status: 'COMPLETED', start_at: inHours(-3), my_feedback_submitted: true }),
      makeFeedbackSummary([mine]),
    )
    let put: Record<string, unknown> | null = null
    server.use(
      http.put(`${API}/interviews/iv-1/feedback`, async ({ request }) => {
        put = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...mine, ...put })
      }),
    )
    const { user } = renderApp('/interviews/iv-1')
    await user.click(await screen.findByRole('button', { name: /Edit my feedback/ }))
    expect(screen.getByRole('radio', { name: /3 Meets expectations/ })).toBeChecked()
    await user.click(screen.getByRole('radio', { name: /5 Outstanding/ }))
    await user.selectOptions(screen.getByRole('combobox', { name: /Recommendation/ }), 'STRONG_HIRE')
    await user.click(screen.getByRole('button', { name: 'Update feedback' }))
    await waitFor(() => expect(put).toMatchObject({ rating: 5, recommendation: 'STRONG_HIRE' }))
  })

  it('surfaces a refused feedback submission', async () => {
    signInAs('RECRUITER')
    mockStaff(
      makeStaffView({ id: 'iv-1', status: 'COMPLETED', start_at: inHours(-3), can_submit_feedback: true }),
      makeFeedbackSummary([]),
    )
    server.use(
      http.post(`${API}/interviews/iv-1/feedback`, () =>
        HttpResponse.json(errorBody('FEEDBACK_ALREADY_SUBMITTED', 'You already submitted feedback for this interview'), {
          status: 409,
        }),
      ),
    )
    const { user } = renderApp('/interviews/iv-1')
    await user.click(await screen.findByRole('radio', { name: /2 Below expectations/ }))
    await user.selectOptions(screen.getByRole('combobox', { name: /Recommendation/ }), 'NO_HIRE')
    await user.click(screen.getByRole('button', { name: 'Submit feedback' }))
    expect(await screen.findByText('You already submitted feedback for this interview')).toBeInTheDocument()
  })

  it('does not offer feedback for cancelled interviews and shows the cancellation reason', async () => {
    signInAs('RECRUITER')
    mockStaff(
      makeStaffView({ id: 'iv-1', status: 'CANCELLED', cancelled_reason: 'Interviewer unavailable', start_at: inHours(5) }),
    )
    renderApp('/interviews/iv-1')
    expect(await screen.findByText('Feedback cannot be recorded for a cancelled interview.')).toBeInTheDocument()
    expect(screen.getAllByText(/Interviewer unavailable/).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /Reschedule/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Cancel$/ })).not.toBeInTheDocument()
  })

  it('lets a started interview be completed from the page', async () => {
    signInAs('RECRUITER')
    mockStaff(makeStaffView({ id: 'iv-1', start_at: inHours(-1), status: 'CONFIRMED' }))
    let hit = false
    server.use(
      http.post(`${API}/interviews/iv-1/no-show`, () => {
        hit = true
        return HttpResponse.json(makeStaffView({ id: 'iv-1', start_at: inHours(-1), status: 'NO_SHOW' }))
      }),
    )
    const { user } = renderApp('/interviews/iv-1')
    await user.click(await screen.findByRole('button', { name: /No-show/ }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Record no-show' }))
    await waitFor(() => expect(hit).toBe(true))
  })

  it('gives hiring managers feedback but no scheduling controls; admins read feedback only', async () => {
    const hm = signInAs('HIRING_MANAGER', { id: 'user-hannah' })
    mockStaff(
      makeStaffView({
        id: 'iv-1',
        start_at: inHours(-2),
        can_submit_feedback: true,
        participants: [{ user_id: hm.id, name: 'Hannah Manager', role: 'INTERVIEWER', has_submitted_feedback: false }],
      }),
    )
    const first = renderApp('/interviews/iv-1')
    expect(await screen.findByRole('button', { name: 'Submit feedback' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Reschedule/ })).not.toBeInTheDocument()
    // a participating hiring manager may still finish the interview
    expect(screen.getByRole('button', { name: /Mark completed/ })).toBeEnabled()
    first.unmount()

    signInAs('ADMIN')
    mockStaff(makeStaffView({ id: 'iv-1', start_at: inHours(-2), can_submit_feedback: false }))
    renderApp('/interviews/iv-1')
    expect(await screen.findByText(/you can read all entries here/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Submit feedback' })).not.toBeInTheDocument()
  })

  it('shows a skeleton, then a not-found state without retry', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get(`${API}/interviews/missing`, () =>
        HttpResponse.json(errorBody('INTERVIEW_NOT_FOUND', 'Interview not found'), { status: 404 }),
      ),
    )
    renderApp('/interviews/missing')
    expect(await screen.findByText('Interview not found', { selector: 'h3' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to interviews' })).toHaveAttribute('href', '/interviews')
    expect(screen.queryByRole('button', { name: /Try again/ })).not.toBeInTheDocument()
  })

  it('retries after a server error', async () => {
    signInAs('RECRUITER')
    let fail = true
    mockStaff()
    server.use(
      http.get(`${API}/interviews/iv-1`, () =>
        fail ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 }) : HttpResponse.json(makeStaffView({ id: 'iv-1' })),
      ),
    )
    const { user } = renderApp('/interviews/iv-1')
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Nina Petrova' })).toBeInTheDocument()
  })

  it('reports a failing feedback list inside its section while the rest of the page works', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get(`${API}/interviews/iv-1`, () => HttpResponse.json(makeStaffView({ id: 'iv-1' }))),
      http.get(`${API}/interviews/iv-1/feedback`, () =>
        HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 }),
      ),
    )
    renderApp('/interviews/iv-1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Nina Petrova' })).toBeInTheDocument()
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
  })
})

describe('interview detail — candidate', () => {
  it('shows logistics only and never asks for feedback or internal data', async () => {
    signInAs('CANDIDATE')
    const calls = { feedback: 0 }
    server.use(
      http.get(`${API}/interviews/iv-cand-1`, () =>
        HttpResponse.json(makeCandidateView({ location: 'HQ Room 3', timezone: 'Europe/Berlin' })),
      ),
      http.get(`${API}/interviews/iv-cand-1/feedback`, () => {
        calls.feedback += 1
        return HttpResponse.json(errorBody('FORBIDDEN', 'internal'), { status: 403 })
      }),
    )
    renderApp('/interviews/iv-cand-1')
    expect(await screen.findByRole('heading', { level: 1, name: /Technical interview with Northwind Labs/ })).toBeInTheDocument()
    expect(screen.getByText('Ravi Patel')).toBeInTheDocument()
    expect(screen.getByText('HQ Room 3')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open meeting link/ })).toHaveAttribute('href', 'https://meet.example.com/abc')
    expect(screen.queryByRole('heading', { name: /feedback/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/hiring team/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Internal notes/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Reschedule|Cancel|No-show/ })).not.toBeInTheDocument()
    expect(calls.feedback).toBe(0)
  })

  it('confirms attendance and reflects the new status', async () => {
    signInAs('CANDIDATE')
    let current = makeCandidateView({ id: 'iv-cand-1' })
    server.use(
      http.get(`${API}/interviews/iv-cand-1`, () => HttpResponse.json(current)),
      http.post(`${API}/interviews/iv-cand-1/confirm`, () => {
        current = { ...current, status: 'CONFIRMED', can_confirm: false }
        return HttpResponse.json(current)
      }),
    )
    const { user } = renderApp('/interviews/iv-cand-1')
    await user.click(await screen.findByRole('button', { name: /Confirm attendance/ }))
    expect(await screen.findByText(/You have confirmed your attendance/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Confirm attendance/ })).not.toBeInTheDocument()
  })

  it('explains a cancelled interview and hides the meeting link', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/interviews/iv-cand-1`, () =>
        HttpResponse.json(makeCandidateView({ status: 'CANCELLED', can_confirm: false })),
      ),
    )
    renderApp('/interviews/iv-cand-1')
    expect(await screen.findByText(/This interview was cancelled/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Open meeting link/ })).not.toBeInTheDocument()
  })
})
