import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import {
  makeCompletion,
  makeInterview,
  makeMyApplication,
  makeRecommendation,
  makeResume,
  recommendationsPage,
} from '@/test/candidateFixtures'
import { errorBody, makeNotification, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const API = '/api/v1'

function mockDashboard(
  over: {
    applications?: ReturnType<typeof makeMyApplication>[]
    interviews?: ReturnType<typeof makeInterview>[]
    recs?: ReturnType<typeof makeRecommendation>[]
    resumes?: ReturnType<typeof makeResume>[]
    completion?: ReturnType<typeof makeCompletion>
  } = {},
) {
  server.use(
    http.get(`${API}/applications`, () =>
      HttpResponse.json(
        page(
          over.applications ?? [
            makeMyApplication({ status: 'APPLIED' }),
            makeMyApplication({ status: 'INTERVIEW' }),
            makeMyApplication({ status: 'OFFER' }),
            makeMyApplication({ status: 'REJECTED' }),
          ],
        ),
      ),
    ),
    http.get(`${API}/interviews`, () =>
      HttpResponse.json(page(over.interviews ?? [makeInterview({ id: 'i1', job_title: 'Data Engineer' })])),
    ),
    http.get(`${API}/recommendations/jobs`, () =>
      HttpResponse.json(
        recommendationsPage(over.recs ?? [makeRecommendation({ id: 'r1', title: 'Platform Engineer' })]),
      ),
    ),
    http.get(`${API}/candidates/me/completion`, () => HttpResponse.json(over.completion ?? makeCompletion())),
    http.get(`${API}/resumes`, () => HttpResponse.json(page(over.resumes ?? []))),
    http.get(`${API}/notifications`, () =>
      HttpResponse.json(
        page([makeNotification({ id: 'n1', title: 'Interview scheduled', message: 'Tuesday at 10:00' })]),
      ),
    ),
  )
}

describe('CandidateDashboardPage', () => {
  it('summarises applications, interviews, recommendations, profile and notifications', async () => {
    signInAs('CANDIDATE')
    mockDashboard({ resumes: [makeResume({ status: 'PROCESSED' })] })
    renderApp('/dashboard')
    expect(await screen.findByRole('heading', { level: 1, name: 'Welcome back, Alex' })).toBeInTheDocument()

    // KPIs
    const kpis = screen.getByRole('region', { name: 'Key figures' })
    await waitFor(() =>
      expect(within(kpis).getByRole('link', { name: /Active applications/ })).toHaveTextContent('3'),
    )
    expect(within(kpis).getByRole('link', { name: /Upcoming interviews/ })).toHaveTextContent('1')
    expect(within(kpis).getByRole('link', { name: /Offers/ })).toHaveTextContent('1')
    expect(within(kpis).getByRole('link', { name: /Profile completeness/ })).toHaveTextContent('70%')

    // applications by status
    const bars = await screen.findByRole('list', { name: 'Applications by status' })
    expect(within(bars).getByRole('link', { name: 'Interview' }).closest('li')).toHaveTextContent('1')
    expect(within(bars).getByRole('link', { name: 'Rejected' })).toHaveAttribute(
      'href',
      '/applications?status=REJECTED',
    )

    // upcoming interview
    const interviews = await screen.findByRole('list', { name: 'Upcoming interviews' })
    expect(within(interviews).getByText('Data Engineer')).toBeInTheDocument()
    expect(within(interviews).getByRole('link', { name: 'Confirm' })).toHaveAttribute('href', '/interviews')

    // recommendations
    const recs = await screen.findByRole('list', { name: 'Top recommended jobs' })
    expect(within(recs).getByRole('heading', { name: 'Platform Engineer' })).toBeInTheDocument()
    expect(within(recs).getByText('82%')).toBeInTheDocument()

    // profile prompts
    const next = await screen.findByRole('list', { name: 'Next steps' })
    expect(within(next).getByRole('link', { name: /Upload your résumé/ })).toHaveAttribute('href', '/resume')
    expect(screen.getByRole('link', { name: 'Review suggestions' })).toHaveAttribute('href', '/resume')

    // notifications
    const notes = await screen.findByRole('list', { name: 'Recent notifications' })
    expect(within(notes).getByText('Interview scheduled')).toBeInTheDocument()
  })

  it('shows helpful empty states for a brand-new candidate', async () => {
    signInAs('CANDIDATE')
    mockDashboard({ applications: [], interviews: [], recs: [], completion: makeCompletion({ percent: 10 }) })
    server.use(http.get(`${API}/notifications`, () => HttpResponse.json(page([]))))
    renderApp('/dashboard')
    expect(await screen.findByRole('heading', { name: 'No applications yet' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'No interviews scheduled' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'No recommendations yet' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: "You're all caught up" })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Browse jobs' })).toHaveAttribute('href', '/jobs')
  })

  it('isolates a failing section and lets the candidate retry it', async () => {
    signInAs('CANDIDATE')
    mockDashboard()
    let calls = 0
    server.use(
      http.get(`${API}/interviews`, () => {
        calls++
        return calls === 1
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(page([makeInterview({ job_title: 'Recovered interview' })]))
      }),
    )
    const { user } = renderApp('/dashboard')
    expect(await screen.findByRole('heading', { name: "Couldn't load interviews" })).toBeInTheDocument()
    // the rest of the page is unaffected
    expect(await screen.findByRole('list', { name: 'Applications by status' })).toBeInTheDocument()
    expect(await screen.findByRole('list', { name: 'Top recommended jobs' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByText('Recovered interview')).toBeInTheDocument()
  })

  it('says when a résumé is still being processed', async () => {
    signInAs('CANDIDATE')
    mockDashboard({
      resumes: [makeResume({ status: 'PROCESSING', processing: { task_status: 'RUNNING', progress: 20 } })],
    })
    renderApp('/dashboard')
    expect(await screen.findByText(/Your résumé is being processed/)).toBeInTheDocument()
  })

  it('congratulates a complete profile', async () => {
    signInAs('CANDIDATE')
    mockDashboard({
      completion: makeCompletion({
        percent: 100,
        items: [{ key: 'headline', label: 'Add a professional headline', weight: 10, done: true }],
        missing: [],
      }),
    })
    renderApp('/dashboard')
    expect(await screen.findByText('Your profile is complete.')).toBeInTheDocument()
  })
})
