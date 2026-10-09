import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { makeCompany, makeMember } from './fixtures'

const API = '/api/v1'

describe('admin companies page', () => {
  it('lists and searches companies', async () => {
    signInAs('ADMIN')
    const seen: URLSearchParams[] = []
    server.use(
      http.get(`${API}/companies`, ({ request }) => {
        seen.push(new URL(request.url).searchParams)
        return HttpResponse.json(
          page([
            makeCompany(),
            makeCompany({ id: 'c-2', name: 'Orbit Finance', status: 'SUSPENDED', industry: 'Fintech' }),
          ]),
        )
      }),
    )
    const { user } = renderApp('/admin/companies')
    const table = await screen.findByRole('table', { name: 'Companies' })
    expect(within(table).getByText('Orbit Finance')).toBeInTheDocument()
    expect(within(table).getByText('Suspended')).toBeInTheDocument()
    await user.type(screen.getByRole('searchbox', { name: /search companies/i }), 'orb')
    await waitFor(() => expect(seen.at(-1)?.get('q')).toBe('orb'))
    await user.click(screen.getByRole('combobox', { name: 'Filter by status' }))
    await user.click(await screen.findByRole('option', { name: 'Active' }))
    await waitFor(() => expect(seen.at(-1)?.get('status')).toBe('ACTIVE'))
  })

  it('suspends a company after confirmation (PATCH status) and reactivates it', async () => {
    signInAs('ADMIN')
    const bodies: unknown[] = []
    let current = makeCompany()
    server.use(
      http.get(`${API}/companies`, () => HttpResponse.json(page([current]))),
      http.patch(`${API}/companies/c-1`, async ({ request }) => {
        const b = (await request.json()) as { status: 'ACTIVE' | 'SUSPENDED' }
        bodies.push(b)
        current = { ...current, status: b.status }
        return HttpResponse.json(current)
      }),
    )
    const { user } = renderApp('/admin/companies')
    await user.click(await screen.findByRole('button', { name: 'Actions for Northwind Labs' }))
    await user.click(await screen.findByRole('menuitem', { name: /suspend/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/hidden from candidates/i)).toBeInTheDocument()
    expect(bodies).toHaveLength(0)
    await user.click(within(dialog).getByRole('button', { name: 'Suspend company' }))
    await waitFor(() => expect(bodies).toEqual([{ status: 'SUSPENDED' }]))
    // The list refetches and now offers reactivation.
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    await user.click(await screen.findByRole('button', { name: 'Actions for Northwind Labs' }))
    await user.click(await screen.findByRole('menuitem', { name: /reactivate/i }))
    await user.click(
      await within(await screen.findByRole('alertdialog')).findByRole('button', {
        name: 'Reactivate company',
      }),
    )
    await waitFor(() => expect(bodies).toEqual([{ status: 'SUSPENDED' }, { status: 'ACTIVE' }]))
  })

  it('opens a details panel with the member count and the company’s jobs', async () => {
    signInAs('ADMIN')
    let jobsQuery: URLSearchParams | null = null
    server.use(
      http.get(`${API}/companies`, () => HttpResponse.json(page([makeCompany()]))),
      http.get(`${API}/companies/c-1/members`, () =>
        HttpResponse.json([
          makeMember(),
          makeMember({
            id: 'm-2',
            first_name: 'Hana',
            last_name: 'Manager',
            role: 'HIRING_MANAGER',
            email: 'hana@x.example',
          }),
        ]),
      ),
      http.get(`${API}/jobs`, ({ request }) => {
        jobsQuery = new URL(request.url).searchParams
        return HttpResponse.json(
          page([makeJobListItem({ id: 'j-1', title: 'Platform Engineer' })], { total: 7 }),
        )
      }),
    )
    const { user } = renderApp('/admin/companies')
    await user.click(await screen.findByRole('button', { name: 'Northwind Labs' }))
    const panel = await screen.findByRole('dialog')
    expect(await within(panel).findByText('Team members (2)')).toBeInTheDocument()
    expect(within(panel).getByText('Hana Manager')).toBeInTheDocument()
    expect(await within(panel).findByText('Jobs (7)')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: 'Platform Engineer' })).toBeInTheDocument()
    expect(within(panel).getByText(/Showing the newest 1 of 7 jobs/)).toBeInTheDocument()
    expect(jobsQuery!.get('company_id')).toBe('c-1')
    expect(within(panel).getByRole('link', { name: /view in users/i })).toHaveAttribute(
      'href',
      '/admin/users?company=c-1',
    )
  })

  it('creates a company and reports a duplicate name on the field', async () => {
    signInAs('ADMIN')
    let attempts = 0
    server.use(
      http.get(`${API}/companies`, () => HttpResponse.json(page([makeCompany()]))),
      http.post(`${API}/companies`, async ({ request }) => {
        attempts += 1
        const b = (await request.json()) as Record<string, unknown>
        if (attempts === 1)
          return HttpResponse.json(
            errorBody('COMPANY_NAME_TAKEN', 'A company with this name already exists'),
            { status: 409 },
          )
        return HttpResponse.json(makeCompany({ id: 'c-9', name: String(b.name) }), { status: 201 })
      }),
    )
    const { user } = renderApp('/admin/companies')
    await user.click(await screen.findByRole('button', { name: 'Create company' }))
    const dialog = await screen.findByRole('dialog', { name: 'Create company' })
    await user.click(within(dialog).getByRole('button', { name: 'Create company' }))
    expect(await within(dialog).findByText(/at least 2 characters/i)).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText(/company name/i), 'Northwind Labs')
    await user.click(within(dialog).getByRole('button', { name: 'Create company' }))
    expect(await within(dialog).findByText('A company with this name already exists')).toBeInTheDocument()
    await user.clear(within(dialog).getByLabelText(/company name/i))
    await user.type(within(dialog).getByLabelText(/company name/i), 'Acme Robotics')
    await user.click(within(dialog).getByRole('button', { name: 'Create company' }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Create company' })).not.toBeInTheDocument(),
    )
    expect(attempts).toBe(2)
  })

  it('handles empty and error states', async () => {
    signInAs('ADMIN')
    let failing = true
    server.use(
      http.get(`${API}/companies`, () =>
        failing
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 })
          : HttpResponse.json(page([])),
      ),
    )
    const { user } = renderApp('/admin/companies')
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    failing = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByText('No companies yet')).toBeInTheDocument()
  })
})
