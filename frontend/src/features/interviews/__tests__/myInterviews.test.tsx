import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeInterview } from '@/test/candidateFixtures'
import { errorBody, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const API = '/api/v1'

describe('MyInterviewsPage', () => {
  it('lists upcoming interviews with logistics and asks only for upcoming ones', async () => {
    signInAs('CANDIDATE')
    let params: URLSearchParams | null = null
    server.use(
      http.get(`${API}/interviews`, ({ request }) => {
        params = new URL(request.url).searchParams
        return HttpResponse.json(page([makeInterview({ id: 'i1', location: 'Berlin HQ, Room 4' })]))
      }),
    )
    renderApp('/interviews')
    expect(await screen.findByRole('heading', { level: 1, name: 'My interviews' })).toBeInTheDocument()
    const card = (await screen.findByRole('heading', { name: /Technical interview/ })).closest('article')!
    expect(params!.get('upcoming_only')).toBe('true')
    expect(params!.get('sort')).toBe('start_asc')
    expect(within(card).getByText('Scheduled')).toBeInTheDocument()
    expect(within(card).getByText('Northwind Labs')).toBeInTheDocument()
    expect(within(card).getByText('Berlin HQ, Room 4')).toBeInTheDocument()
    expect(within(card).getByText(/Riley Recruiter/)).toBeInTheDocument()
    const join = within(card).getByRole('link', { name: /Join video call/ })
    expect(join).toHaveAttribute('href', 'https://meet.example.com/abc')
    expect(join).toHaveAttribute('rel', 'noopener noreferrer')
    expect(within(card).getByText('60 min', { exact: false })).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: 'View job' })).toHaveAttribute('href', '/jobs/job-1')
  })

  it('confirms attendance and updates the card', async () => {
    signInAs('CANDIDATE')
    let current = makeInterview({ id: 'i1' })
    server.use(
      http.get(`${API}/interviews`, () => HttpResponse.json(page([current]))),
      http.post(`${API}/interviews/i1/confirm`, () => {
        current = { ...current, status: 'CONFIRMED', can_confirm: false }
        return HttpResponse.json(current)
      }),
    )
    const { user } = renderApp('/interviews')
    await user.click(await screen.findByRole('button', { name: /Confirm attendance/ }))
    expect(await screen.findByText('Attendance confirmed')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Confirm attendance/ })).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Confirmed')).toBeInTheDocument()
  })

  it('reports a conflict when the interview can no longer be confirmed', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/interviews`, () => HttpResponse.json(page([makeInterview({ id: 'i1' })]))),
      http.post(`${API}/interviews/i1/confirm`, () =>
        HttpResponse.json(errorBody('INVALID_STATE_TRANSITION', 'cancelled'), { status: 409 }),
      ),
    )
    const { user } = renderApp('/interviews')
    await user.click(await screen.findByRole('button', { name: /Confirm attendance/ }))
    expect(await screen.findByText('Could not confirm the interview')).toBeInTheDocument()
    expect(screen.getByText(/status changed/)).toBeInTheDocument()
  })

  it('switches to past interviews (closed statuses, newest first)', async () => {
    signInAs('CANDIDATE')
    const seen: URLSearchParams[] = []
    server.use(
      http.get(`${API}/interviews`, ({ request }) => {
        const p = new URL(request.url).searchParams
        seen.push(p)
        return HttpResponse.json(
          p.get('upcoming_only')
            ? page([makeInterview({ id: 'up' })])
            : page([
                makeInterview({
                  id: 'old',
                  status: 'COMPLETED',
                  can_confirm: false,
                  interview_type: 'FINAL',
                }),
              ]),
        )
      }),
    )
    const { user, router } = renderApp('/interviews')
    await screen.findByRole('heading', { name: /Technical interview/ })
    await user.click(screen.getByRole('tab', { name: 'Past' }))
    expect(await screen.findByRole('heading', { name: /Final interview/ })).toBeInTheDocument()
    expect(router.state.location.search).toBe('?view=past')
    const last = seen.at(-1)!
    expect(last.getAll('status')).toEqual(['COMPLETED', 'CANCELLED', 'NO_SHOW'])
    expect(last.get('sort')).toBe('start_desc')
    expect(screen.queryByRole('button', { name: /Confirm attendance/ })).not.toBeInTheDocument()
  })

  it('shows empty states per tab', async () => {
    signInAs('CANDIDATE')
    server.use(http.get(`${API}/interviews`, () => HttpResponse.json(page([]))))
    renderApp('/interviews')
    expect(await screen.findByRole('heading', { name: 'No upcoming interviews' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View my applications' })).toHaveAttribute(
      'href',
      '/applications',
    )
  })

  it('shows an error state with retry', async () => {
    signInAs('CANDIDATE')
    let calls = 0
    server.use(
      http.get(`${API}/interviews`, () => {
        calls++
        return calls === 1
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(page([makeInterview()]))
      }),
    )
    const { user } = renderApp('/interviews')
    expect(await screen.findByRole('heading', { name: "Couldn't load your interviews" })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByRole('heading', { name: /Technical interview/ })).toBeInTheDocument()
  })

  it('tells the candidate that a rescheduled interview needs re-confirmation', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/interviews`, () =>
        HttpResponse.json(page([makeInterview({ status: 'RESCHEDULED' })])),
      ),
    )
    renderApp('/interviews')
    expect(await screen.findByText(/The time changed/)).toBeInTheDocument()
  })
})
