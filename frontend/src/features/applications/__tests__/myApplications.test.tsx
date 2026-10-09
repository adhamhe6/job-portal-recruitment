import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeMyApplication } from '@/test/candidateFixtures'
import { errorBody, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const API = '/api/v1'

describe('MyApplicationsPage', () => {
  it('lists my applications with status, dates and links, and offers withdraw only while screening', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/applications`, () =>
        HttpResponse.json(
          page([
            makeMyApplication({ id: 'a1', job_id: 'job-9', job_title: 'Data Engineer', status: 'SCREENING' }),
            makeMyApplication({
              id: 'a2',
              job_title: 'Platform Engineer',
              status: 'SHORTLISTED',
              match_score: 0.8,
              match_band: 'STRONG',
            }),
          ]),
        ),
      ),
    )
    renderApp('/applications')
    expect(await screen.findByRole('heading', { level: 1, name: 'My applications' })).toBeInTheDocument()
    const first = (await screen.findByRole('heading', { name: 'Data Engineer' })).closest('article')!
    expect(within(first).getByText('Screening')).toBeInTheDocument()
    expect(within(first).getByRole('link', { name: 'Data Engineer' })).toHaveAttribute('href', '/jobs/job-9')
    expect(
      within(first).getByRole('button', { name: 'Withdraw application for Data Engineer' }),
    ).toBeInTheDocument()
    const second = screen.getByRole('heading', { name: 'Platform Engineer' }).closest('article')!
    expect(within(second).getByText('Shortlisted')).toBeInTheDocument()
    expect(within(second).queryByRole('button', { name: /Withdraw/ })).not.toBeInTheDocument()
  })

  it('sends the status filter and sort from the URL to the API and can change them', async () => {
    signInAs('CANDIDATE')
    const seen: URLSearchParams[] = []
    server.use(
      http.get(`${API}/applications`, ({ request }) => {
        seen.push(new URL(request.url).searchParams)
        return HttpResponse.json(page([makeMyApplication({ status: 'SCREENING' })]))
      }),
    )
    const { user, router } = renderApp('/applications?status=SCREENING&sort=updated')
    await screen.findByRole('heading', { name: 'Senior Backend Engineer' })
    expect(seen[0]?.get('status')).toBe('SCREENING')
    expect(seen[0]?.get('sort')).toBe('updated')

    await user.click(screen.getByRole('combobox', { name: 'Status' }))
    await user.click(await screen.findByRole('option', { name: 'Offer' }))
    await waitFor(() => expect(router.state.location.search).toContain('status=OFFER'))
    await waitFor(() => expect(seen.at(-1)?.get('status')).toBe('OFFER'))
  })

  it('withdraws after confirmation, sending the optional reason', async () => {
    signInAs('CANDIDATE')
    let items = [makeMyApplication({ id: 'a1', job_title: 'Data Engineer', status: 'APPLIED' })]
    let body: unknown = null
    server.use(
      http.get(`${API}/applications`, () => HttpResponse.json(page(items))),
      http.post(`${API}/applications/a1/withdraw`, async ({ request }) => {
        body = await request.json()
        items = [{ ...items[0]!, status: 'WITHDRAWN' }]
        return HttpResponse.json({})
      }),
    )
    const { user } = renderApp('/applications')
    await user.click(await screen.findByRole('button', { name: 'Withdraw application for Data Engineer' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Data Engineer')
    await user.type(within(dialog).getByLabelText(/Reason/), 'Accepted another offer')
    await user.click(within(dialog).getByRole('button', { name: 'Withdraw application' }))
    await waitFor(() => expect(body).toEqual({ comment: 'Accepted another offer' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    const card = screen.getByRole('heading', { name: 'Data Engineer' }).closest('article')!
    expect(await within(card).findByText('Withdrawn')).toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: /Withdraw/ })).not.toBeInTheDocument()
  })

  it('keeps the dialog open and explains when the backend refuses the withdrawal', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/applications`, () =>
        HttpResponse.json(page([makeMyApplication({ id: 'a1', status: 'SCREENING' })])),
      ),
      http.post(`${API}/applications/a1/withdraw`, () =>
        HttpResponse.json(errorBody('CANNOT_WITHDRAW', 'past screening'), { status: 422 }),
      ),
    )
    const { user } = renderApp('/applications')
    await user.click(await screen.findByRole('button', { name: /Withdraw application for/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Withdraw application' }))
    expect(await within(dialog).findByText(/no longer be withdrawn here/)).toBeInTheDocument()
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  })

  it('shows the status timeline when the history is expanded', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.get(`${API}/applications`, () =>
        HttpResponse.json(page([makeMyApplication({ id: 'a1', status: 'SCREENING' })])),
      ),
      http.get(`${API}/applications/a1/history`, () =>
        HttpResponse.json([
          {
            id: 'h1',
            from_status: null,
            to_status: 'APPLIED',
            actor_name: 'Alex Rivera',
            comment: null,
            created_at: '2026-10-01T10:00:00Z',
          },
          {
            id: 'h2',
            from_status: 'APPLIED',
            to_status: 'SCREENING',
            actor_name: 'Riley Recruiter',
            comment: 'Looks promising',
            created_at: '2026-10-03T10:00:00Z',
          },
        ]),
      ),
    )
    const { user } = renderApp('/applications')
    const toggle = await screen.findByRole('button', { name: 'Status history' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByText('Moved to Screening')).toBeInTheDocument()
    expect(screen.getByText('Application submitted')).toBeInTheDocument()
    expect(screen.getByText(/Looks promising/)).toBeInTheDocument()
  })

  it('shows an empty state with next steps when there are no applications', async () => {
    signInAs('CANDIDATE')
    server.use(http.get(`${API}/applications`, () => HttpResponse.json(page([]))))
    renderApp('/applications')
    expect(
      await screen.findByRole('heading', { name: "You haven't applied to any jobs yet" }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'See recommendations' })).toHaveAttribute('href', '/recommended')
  })

  it('shows a filter-specific empty state that can clear the filter', async () => {
    signInAs('CANDIDATE')
    server.use(http.get(`${API}/applications`, () => HttpResponse.json(page([]))))
    const { user, router } = renderApp('/applications?status=HIRED')
    expect(
      await screen.findByRole('heading', { name: 'No applications with this status' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show all applications' }))
    await waitFor(() => expect(router.state.location.search).toBe(''))
  })

  it('shows an error state with retry', async () => {
    signInAs('CANDIDATE')
    let calls = 0
    server.use(
      http.get(`${API}/applications`, () => {
        calls++
        return calls === 1
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(page([makeMyApplication()]))
      }),
    )
    const { user } = renderApp('/applications')
    expect(
      await screen.findByRole('heading', { name: "Couldn't load your applications" }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByRole('heading', { name: 'Senior Backend Engineer' })).toBeInTheDocument()
  })

  it('paginates', async () => {
    signInAs('CANDIDATE')
    const pages: string[] = []
    server.use(
      http.get(`${API}/applications`, ({ request }) => {
        const p = new URL(request.url).searchParams.get('page') ?? '1'
        pages.push(p)
        return HttpResponse.json(
          page([makeMyApplication({ job_title: `Job on page ${p}` })], {
            page: Number(p),
            pages: 2,
            total: 12,
            page_size: 10,
          }),
        )
      }),
    )
    const { user } = renderApp('/applications')
    await screen.findByRole('heading', { name: 'Job on page 1' })
    await user.click(screen.getByRole('button', { name: /Next/ }))
    expect(await screen.findByRole('heading', { name: 'Job on page 2' })).toBeInTheDocument()
  })
})
