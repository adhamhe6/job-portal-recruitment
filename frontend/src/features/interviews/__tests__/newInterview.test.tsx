import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { COMPANY_ID, errorBody, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { makeMember } from './fixtures'

const API = '/api/v1'

function baseHandlers() {
  server.use(
    http.get(`${API}/interviews`, () => HttpResponse.json(page([]))),
    http.get(`${API}/jobs`, () => HttpResponse.json(page([]))),
    http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([makeMember('user-recruiter', 'Riley')])),
  )
}

describe('schedule from the interviews page', () => {
  it('picks a shortlisted application, then opens the schedule dialog for it', async () => {
    signInAs('RECRUITER')
    baseHandlers()
    const queries: URLSearchParams[] = []
    server.use(
      http.get(`${API}/applications`, ({ request }) => {
        queries.push(new URL(request.url).searchParams)
        return HttpResponse.json(
          page([
            { id: 'app-1', candidate_name: 'Nina Petrova', job_title: 'Senior Backend Engineer', status: 'SHORTLISTED' },
            { id: 'app-2', candidate_name: 'Alex Rivera', job_title: 'Data Analyst', status: 'INTERVIEW' },
          ]),
        )
      }),
      http.get(`${API}/applications/app-1`, () =>
        HttpResponse.json({
          id: 'app-1',
          job_id: 'job-1',
          job_title: 'Senior Backend Engineer',
          company_id: COMPANY_ID,
          candidate_name: 'Nina Petrova',
          status: 'SHORTLISTED',
        }),
      ),
      http.get(`${API}/jobs/job-1`, () => HttpResponse.json({ id: 'job-1', hiring_manager_id: null })),
    )
    const { user } = renderApp('/interviews')
    await user.click(await screen.findByRole('button', { name: 'Schedule interview' }))
    const picker = await screen.findByRole('dialog', { name: 'Schedule an interview' })
    await user.click(within(picker).getByRole('combobox', { name: /Application/ }))
    await user.click(await screen.findByRole('option', { name: /Nina Petrova — Senior Backend Engineer/ }))

    const dialog = await screen.findByRole('dialog', { name: 'Schedule interview' })
    expect(await within(dialog).findByText('Senior Backend Engineer', { exact: false })).toBeInTheDocument()
    expect(await within(dialog).findByLabelText(/^Starts/)).toBeInTheDocument()
    expect(queries[0]!.getAll('status')).toEqual(['SHORTLISTED', 'INTERVIEW'])
  })

  it('tells the user when nobody is ready to be interviewed', async () => {
    signInAs('RECRUITER')
    baseHandlers()
    server.use(http.get(`${API}/applications`, () => HttpResponse.json(page([]))))
    const { user } = renderApp('/interviews')
    await user.click(await screen.findByRole('button', { name: 'Schedule interview' }))
    expect(await screen.findByText('No applications are ready to interview')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to applications' })).toHaveAttribute('href', '/applications')
  })

  it('shows an error with retry when applications cannot be loaded', async () => {
    signInAs('RECRUITER')
    baseHandlers()
    server.use(
      http.get(`${API}/applications`, () => HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })),
    )
    const { user } = renderApp('/interviews')
    await user.click(await screen.findByRole('button', { name: 'Schedule interview' }))
    const dialog = await screen.findByRole('dialog', { name: 'Schedule an interview' })
    expect(await within(dialog).findByText('Service unavailable')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /Try again/ })).toBeInTheDocument()
  })
})
