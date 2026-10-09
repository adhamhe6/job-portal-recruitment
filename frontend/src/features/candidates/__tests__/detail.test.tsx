import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { errorBody, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { JOB_ID, makeCandidateView, makeMatchDetail } from './testData'

const JOBS = [
  makeJobListItem({ id: 'job-other', title: 'Frontend Engineer' }),
  makeJobListItem({ id: JOB_ID, title: 'Machine Learning Engineer' }),
]

function mockApi(
  view = makeCandidateView(),
  detail: ReturnType<typeof makeMatchDetail> | null = makeMatchDetail(),
) {
  const requests: URL[] = []
  server.use(
    http.get('/api/v1/candidates/:id', ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json(view)
    }),
    http.get('/api/v1/jobs', () => HttpResponse.json(page(JOBS))),
    http.get('/api/v1/matches/jobs/:jobId/candidates/:cid', ({ params }) =>
      detail
        ? HttpResponse.json({ ...detail, job_id: String(params.jobId) })
        : HttpResponse.json(errorBody('MATCH_NOT_FOUND', 'No match'), { status: 404 }),
    ),
  )
  return requests
}

afterEach(() => vi.restoreAllMocks())

describe('candidate detail (staff)', () => {
  it('shows the full profile: summary, skills, experience, education, languages and contact', async () => {
    signInAs('RECRUITER')
    mockApi()
    renderApp('/candidates/cand-1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Priya Nair' })).toBeInTheDocument()
    expect(screen.getByText('Statistician who builds NLP classifiers.')).toBeInTheDocument()
    expect(screen.getByText('Python (Advanced · 4 yrs)')).toBeInTheDocument()
    // suggested, unconfirmed skills are kept apart
    const unconfirmed = screen.getByRole('list', { name: 'Unconfirmed skills' })
    expect(within(unconfirmed).getByText('Rust')).toBeInTheDocument()
    expect(screen.getByText('Data Scientist')).toBeInTheDocument()
    expect(screen.getByText(/Clickstream/)).toBeInTheDocument()
    expect(screen.getByText('MSc Statistics')).toBeInTheDocument()
    expect(screen.getByText('English')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'priya.nair@demo.example' })).toHaveAttribute(
      'href',
      'mailto:priya.nair@demo.example',
    )
    expect(screen.getByText('+49 30 1234567')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /GitHub/ })).toHaveAttribute(
      'rel',
      expect.stringContaining('noopener'),
    )
  })

  it('lists applications to this company with links, and defaults the match to the applied job', async () => {
    signInAs('RECRUITER')
    const requests = mockApi()
    renderApp('/candidates/cand-1')
    const apps = await screen.findByRole('list', { name: 'Applications' })
    expect(within(apps).getByRole('link', { name: 'Machine Learning Engineer' })).toHaveAttribute(
      'href',
      '/applications/app-9',
    )
    expect(within(apps).getByText('Screening')).toBeInTheDocument()
    // match for the applied job is explained with weights and skill gaps
    expect(await screen.findByText('Score breakdown')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Job' })).toHaveValue(JOB_ID)
    expect(screen.getByText('PyTorch')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /where they rank/i })).toHaveAttribute(
      'href',
      `/matching/${JOB_ID}`,
    )
    expect(requests[0]!.searchParams.has('job_id')).toBe(false)
  })

  it('switching the job in the picker loads that match and keeps it in the URL', async () => {
    signInAs('RECRUITER')
    mockApi()
    const { user, router } = renderApp('/candidates/cand-1')
    const select = await screen.findByRole('combobox', { name: 'Job' })
    await screen.findByRole('option', { name: /Frontend Engineer/ })
    await user.selectOptions(select, 'job-other')
    await waitFor(() => expect(router.state.location.search).toContain('job_id=job-other'))
    expect(await screen.findByText('Score breakdown')).toBeInTheDocument()
  })

  it('says so when no match was computed for the chosen job', async () => {
    signInAs('RECRUITER')
    mockApi(makeCandidateView(), null)
    renderApp('/candidates/cand-1')
    expect(await screen.findByText(/No match has been computed/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open ranking for this job/ })).toBeInTheDocument()
  })

  it('downloads the résumé through the authorised endpoint', async () => {
    signInAs('RECRUITER')
    mockApi()
    let fileRequested = false
    server.use(
      http.get('/api/v1/resumes/res-1/file', () => {
        fileRequested = true
        return new HttpResponse('%PDF-1.4', {
          headers: {
            'Content-Type': 'application/pdf',
            'Content-Disposition': 'attachment; filename="priya-nair.pdf"',
          },
        })
      }),
    )
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { user } = renderApp('/candidates/cand-1')
    await user.click(await screen.findByRole('button', { name: 'Download priya-nair.pdf' }))
    await waitFor(() => expect(fileRequested).toBe(true))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
  })

  it('reports a failed résumé download without leaving the page', async () => {
    signInAs('RECRUITER')
    mockApi()
    server.use(
      http.get('/api/v1/resumes/res-1/file', () =>
        HttpResponse.json(errorBody('RESUME_NOT_FOUND', 'Résumé not found'), { status: 404 }),
      ),
    )
    const { user } = renderApp('/candidates/cand-1')
    await user.click(await screen.findByRole('button', { name: 'Download priya-nair.pdf' }))
    expect(await screen.findByText('Couldn’t download the résumé')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Priya Nair' })).toBeInTheDocument()
  })

  it('limits a marketplace profile: no contact details, résumés or applications', async () => {
    signInAs('RECRUITER')
    mockApi(
      makeCandidateView({
        access: 'PROFILE',
        email: null,
        phone: null,
        resumes: [],
        applications: [],
      }),
    )
    renderApp('/candidates/cand-1')
    expect(await screen.findByText('Limited view')).toBeInTheDocument()
    expect(screen.getByText(/Contact details are only released/)).toBeInTheDocument()
    expect(screen.queryByText('priya.nair@demo.example')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Résumés' })).not.toBeInTheDocument()
    expect(screen.getByText(/has not applied to any of your jobs/)).toBeInTheDocument()
    // no applied job to default to: asks to choose one
    expect(screen.getByText(/Choose one of your company’s jobs/)).toBeInTheDocument()
  })

  it('shows "not found" without revealing whether the candidate exists (404)', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/candidates/:id', () =>
        HttpResponse.json(errorBody('CANDIDATE_NOT_FOUND', 'Candidate not found'), { status: 404 }),
      ),
    )
    renderApp('/candidates/zzz')
    expect(await screen.findByRole('heading', { name: 'Candidate not found' })).toBeInTheDocument()
    expect(screen.getByText(/imported by your company/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to candidates' })).toHaveAttribute('href', '/candidates')
  })

  it('shows access denied for a 403 and offers a retry for server errors', async () => {
    signInAs('HIRING_MANAGER')
    server.use(
      http.get('/api/v1/candidates/:id', () =>
        HttpResponse.json(errorBody('FORBIDDEN', 'no'), { status: 403 }),
      ),
    )
    renderApp('/candidates/cand-1')
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
  })

  it('retries after a server error', async () => {
    signInAs('RECRUITER')
    let fail = true
    mockApi()
    server.use(
      http.get('/api/v1/candidates/:id', () =>
        fail
          ? HttpResponse.json(errorBody('X', 'boom'), { status: 500 })
          : HttpResponse.json(makeCandidateView()),
      ),
    )
    const { user } = renderApp('/candidates/cand-1')
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Priya Nair' })).toBeInTheDocument()
  })
})
