import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { makeApplicationDetail, makeNote, MATCH_DETAIL } from './fixtures'

function staffHandlers(
  detail = makeApplicationDetail(),
  notes = [makeNote({ body: 'Strong phone screen.' })],
) {
  const seen = { notes: 0, match: 0 }
  server.use(
    http.get('/api/v1/applications/app-1', () => HttpResponse.json(detail)),
    http.get('/api/v1/applications/app-1/notes', () => {
      seen.notes++
      return HttpResponse.json(notes)
    }),
    http.get('/api/v1/matches/jobs/job-1/candidates/cand-9', () => {
      seen.match++
      return HttpResponse.json(MATCH_DETAIL)
    }),
    http.get('/api/v1/interviews', () =>
      HttpResponse.json(
        page([
          {
            id: 'iv-1',
            application_id: 'app-1',
            interview_type: 'TECHNICAL',
            start_at: '2026-10-20T09:00:00Z',
            end_at: '2026-10-20T10:00:00Z',
            timezone: 'UTC',
            status: 'SCHEDULED',
            location: null,
            meeting_url: 'https://meet.example.com/x',
          },
        ]),
      ),
    ),
  )
  return seen
}

describe('application detail (staff)', () => {
  it('shows the candidate, match explanation, cover letter, audited history, notes and interviews', async () => {
    signInAs('RECRUITER')
    staffHandlers()
    renderApp('/applications/app-1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Dana Candidate' })).toBeInTheDocument()
    expect(screen.getByText('Applied for Senior Backend Engineer')).toBeInTheDocument()

    // match: score + strong / related / missing skills
    expect(await screen.findByText('Strong — has')).toBeInTheDocument()
    expect(screen.getAllByText('Python').length).toBeGreaterThan(0)
    expect(screen.getByText('Memcached ≈ Redis')).toBeInTheDocument()
    expect(screen.getByText('Kafka')).toBeInTheDocument()
    expect(screen.getByText(/6 years vs 4\+ years required/)).toBeInTheDocument()

    expect(screen.getByText('I love distributed systems.')).toBeInTheDocument()
    // history timeline with actors and comments
    expect(screen.getByText('By Riley Recruiter')).toBeInTheDocument()
    expect(screen.getByText('“Looks promising”')).toBeInTheDocument()
    // notes + interviews
    expect(await screen.findByText('Strong phone screen.')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Technical' })).toHaveAttribute('href', '/interviews/iv-1')
    expect(screen.getByRole('button', { name: /Download dana\.pdf/ })).toBeInTheDocument()
  })

  it('moves the application forward and rejects with a reason from the workflow buttons', async () => {
    signInAs('RECRUITER')
    staffHandlers()
    const bodies: unknown[] = []
    const moved = makeApplicationDetail({
      status: 'SHORTLISTED',
      allowed_next_statuses: ['INTERVIEW', 'REJECTED'],
    })
    server.use(
      http.get('/api/v1/applications/app-1', () =>
        HttpResponse.json(bodies.length ? moved : makeApplicationDetail()),
      ),
      http.post('/api/v1/applications/app-1/status', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(
          makeApplicationDetail({ status: 'SHORTLISTED', allowed_next_statuses: ['INTERVIEW', 'REJECTED'] }),
        )
      }),
    )
    const { user } = renderApp('/applications/app-1')
    await user.click(await screen.findByRole('button', { name: /Shortlist/ }))
    await waitFor(() => expect(bodies).toEqual([{ status: 'SHORTLISTED', comment: null }]))
    expect(await screen.findByRole('button', { name: /Move to interview/ })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Reject/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.type(within(dialog).getByLabelText(/Reason/), 'Salary mismatch')
    await user.click(within(dialog).getByRole('button', { name: 'Reject application' }))
    await waitFor(() => expect(bodies[1]).toEqual({ status: 'REJECTED', comment: 'Salary mismatch' }))
  })

  it('keeps the reject dialog open and explains a refusal', async () => {
    signInAs('RECRUITER')
    staffHandlers()
    server.use(
      http.post('/api/v1/applications/app-1/status', () =>
        HttpResponse.json(errorBody('INVALID_STATE_TRANSITION', 'x', { from: 'HIRED', to: 'REJECTED' }), {
          status: 409,
        }),
      ),
    )
    const { user } = renderApp('/applications/app-1')
    await user.click(await screen.findByRole('button', { name: /Reject/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Reject application' }))
    expect(await within(dialog).findByText("That move isn't possible")).toBeInTheDocument()
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  })

  it('adds an internal note and shows it at the top', async () => {
    signInAs('RECRUITER')
    staffHandlers()
    let body: unknown
    const created = makeNote({ id: 'new', body: 'Call scheduled for Friday.' })
    server.use(
      http.get('/api/v1/applications/app-1/notes', () =>
        HttpResponse.json(
          body
            ? [created, makeNote({ body: 'Strong phone screen.' })]
            : [makeNote({ body: 'Strong phone screen.' })],
        ),
      ),
      http.post('/api/v1/applications/app-1/notes', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const { user } = renderApp('/applications/app-1')
    await screen.findByText('Strong phone screen.')
    await user.type(screen.getByLabelText('Add a note'), '  Call scheduled for Friday.  ')
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await waitFor(() => expect(body).toEqual({ body: 'Call scheduled for Friday.' }))
    expect(await screen.findByText('Call scheduled for Friday.')).toBeInTheDocument()
    expect(screen.getByLabelText('Add a note')).toHaveValue('')
  })

  it('validates an empty note without calling the API', async () => {
    signInAs('RECRUITER')
    staffHandlers()
    const { user } = renderApp('/applications/app-1')
    await screen.findByText('Strong phone screen.')
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    expect(await screen.findByText('Write a note before saving.')).toBeInTheDocument()
  })

  it('offers "Schedule interview" only for shortlisted/interview applications and links to the interviews area', async () => {
    signInAs('RECRUITER')
    staffHandlers(
      makeApplicationDetail({ status: 'SHORTLISTED', allowed_next_statuses: ['INTERVIEW', 'REJECTED'] }),
    )
    renderApp('/applications/app-1')
    expect(await screen.findByRole('link', { name: 'Schedule interview' })).toHaveAttribute(
      'href',
      '/interviews?application_id=app-1',
    )
  })

  it('does not offer scheduling before shortlisting and shows an empty interviews state', async () => {
    signInAs('RECRUITER')
    staffHandlers()
    server.use(http.get('/api/v1/interviews', () => HttpResponse.json(page([]))))
    renderApp('/applications/app-1')
    expect(await screen.findByText('No interviews yet')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Schedule interview' })).not.toBeInTheDocument()
    expect(screen.getByText(/once the application is shortlisted/)).toBeInTheDocument()
  })

  it('is read-only for hiring managers: no workflow buttons', async () => {
    signInAs('HIRING_MANAGER')
    staffHandlers()
    renderApp('/applications/app-1')
    await screen.findByRole('heading', { level: 1, name: 'Dana Candidate' })
    expect(screen.getByText(/read-only access/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Shortlist/ })).not.toBeInTheDocument()
  })

  it('shows an error with retry, and a not-found message for missing applications', async () => {
    signInAs('RECRUITER')
    staffHandlers()
    let fail = true
    server.use(
      http.get('/api/v1/applications/app-1', () =>
        fail
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 })
          : HttpResponse.json(makeApplicationDetail()),
      ),
    )
    const { user } = renderApp('/applications/app-1')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Dana Candidate' })).toBeInTheDocument()
  })

  it('reports a missing application', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/applications/nope', () =>
        HttpResponse.json(errorBody('APPLICATION_NOT_FOUND', 'Application not found'), { status: 404 }),
      ),
    )
    renderApp('/applications/nope')
    expect(await screen.findByRole('heading', { name: 'Application not found' })).toBeInTheDocument()
  })
})

describe('application detail (candidate)', () => {
  const candidateView = (o = {}) =>
    makeApplicationDetail({
      status: 'SCREENING',
      match: null,
      allowed_next_statuses: [],
      history: [
        {
          id: 'h1',
          from_status: null,
          to_status: 'APPLIED',
          actor_name: 'You',
          comment: null,
          created_at: '2026-10-01T10:00:00Z',
        },
        {
          id: 'h2',
          from_status: 'APPLIED',
          to_status: 'SCREENING',
          actor_name: 'Hiring team',
          comment: null,
          created_at: '2026-10-03T10:00:00Z',
        },
      ],
      ...o,
    })

  it('shows only candidate-safe information and never requests notes, match or interviews', async () => {
    signInAs('CANDIDATE')
    const requested: string[] = []
    server.use(
      http.get('/api/v1/applications/app-1', () => HttpResponse.json(candidateView())),
      http.get('/api/v1/applications/app-1/notes', () => {
        requested.push('notes')
        return HttpResponse.json([])
      }),
      http.get('/api/v1/matches/jobs/:j/candidates/:c', () => {
        requested.push('match')
        return HttpResponse.json(MATCH_DETAIL)
      }),
    )
    renderApp('/applications/app-1')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Senior Backend Engineer' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/By Hiring team/)).toBeInTheDocument()
    expect(screen.getByText('Your cover letter')).toBeInTheDocument()
    expect(screen.queryByText('Internal notes')).not.toBeInTheDocument()
    expect(screen.queryByText(/Match with this job/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Shortlist|Reject/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Interviews')).not.toBeInTheDocument()
    expect(requested).toEqual([])
  })

  it('lets the candidate withdraw before shortlisting, with an optional reason', async () => {
    signInAs('CANDIDATE')
    let body: unknown
    server.use(
      http.get('/api/v1/applications/app-1', () =>
        HttpResponse.json(candidateView(body ? { status: 'WITHDRAWN' } : {})),
      ),
      http.post('/api/v1/applications/app-1/withdraw', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(candidateView({ status: 'WITHDRAWN' }))
      }),
    )
    const { user } = renderApp('/applications/app-1')
    await user.click(await screen.findByRole('button', { name: /Withdraw/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.type(within(dialog).getByLabelText(/Reason/), 'Accepted another offer')
    await user.click(within(dialog).getByRole('button', { name: 'Withdraw application' }))
    await waitFor(() => expect(body).toEqual({ comment: 'Accepted another offer' }))
    expect(await screen.findByText('You withdrew this application.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Withdraw/ })).not.toBeInTheDocument()
  })

  it('hides withdraw once shortlisted and explains a refused withdrawal', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get('/api/v1/applications/app-1', () =>
        HttpResponse.json(candidateView({ status: 'SHORTLISTED' })),
      ),
    )
    renderApp('/applications/app-1')
    await screen.findByRole('heading', { level: 1, name: 'Senior Backend Engineer' })
    expect(screen.queryByRole('button', { name: /Withdraw/ })).not.toBeInTheDocument()
  })

  it('explains CANNOT_WITHDRAW inside the dialog', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get('/api/v1/applications/app-1', () => HttpResponse.json(candidateView())),
      http.post('/api/v1/applications/app-1/withdraw', () =>
        HttpResponse.json(errorBody('CANNOT_WITHDRAW', 'past screening'), { status: 422 }),
      ),
    )
    const { user } = renderApp('/applications/app-1')
    await user.click(await screen.findByRole('button', { name: /Withdraw/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Withdraw application' }))
    expect(await within(dialog).findByText("This application can't be withdrawn")).toBeInTheDocument()
  })
})
