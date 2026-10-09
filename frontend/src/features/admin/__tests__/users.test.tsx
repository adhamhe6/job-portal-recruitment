import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { makeAdminUser, makeCompany } from './fixtures'

const API = '/api/v1'

function mockCompanies() {
  server.use(
    http.get(`${API}/companies`, () =>
      HttpResponse.json(page([makeCompany(), makeCompany({ id: 'c-2', name: 'Orbit Finance' })])),
    ),
  )
}

describe('admin users page', () => {
  it('lists users with role, company and status, and sends filters to the API', async () => {
    signInAs('ADMIN')
    mockCompanies()
    const seen: URLSearchParams[] = []
    server.use(
      http.get(`${API}/users`, ({ request }) => {
        seen.push(new URL(request.url).searchParams)
        return HttpResponse.json(
          page([
            makeAdminUser(),
            makeAdminUser({
              id: 'u-2',
              first_name: 'Sam',
              last_name: 'Suspended',
              email: 'sam@x.example',
              role: 'RECRUITER',
              company_id: 'c-1',
              status: 'SUSPENDED',
            }),
          ]),
        )
      }),
    )
    const { user } = renderApp('/admin/users')
    expect(await screen.findByRole('heading', { name: 'Users', level: 1 })).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'Users' })
    expect(within(table).getByText('Jo Candidate')).toBeInTheDocument()
    expect(within(table).getByText('Suspended')).toBeInTheDocument()
    expect(await within(table).findByText('Northwind Labs')).toBeInTheDocument()

    await user.type(screen.getByRole('searchbox', { name: /search users/i }), 'sam')
    await waitFor(() => expect(seen.at(-1)?.get('q')).toBe('sam'))
    await user.click(screen.getByRole('combobox', { name: 'Filter by role' }))
    await user.click(await screen.findByRole('option', { name: 'Recruiter' }))
    await waitFor(() => expect(seen.at(-1)?.get('role')).toBe('RECRUITER'))
    await user.click(screen.getByRole('combobox', { name: 'Filter by status' }))
    await user.click(await screen.findByRole('option', { name: 'Suspended' }))
    await waitFor(() => expect(seen.at(-1)?.get('status')).toBe('SUSPENDED'))
    expect(screen.getByRole('list', { name: 'Active filters' })).toBeInTheDocument()
  })

  it('deactivates a user only after confirmation and shows the API error inside the dialog', async () => {
    signInAs('ADMIN')
    mockCompanies()
    const bodies: unknown[] = []
    let fail = true
    server.use(
      http.get(`${API}/users`, () =>
        HttpResponse.json(page([makeAdminUser({ id: 'u-9', first_name: 'Dana', last_name: 'Doe' })])),
      ),
      http.patch(`${API}/users/u-9`, async ({ request }) => {
        bodies.push(await request.json())
        return fail
          ? HttpResponse.json(errorBody('SELF_MODIFICATION', 'nope'), { status: 422 })
          : HttpResponse.json(makeAdminUser({ id: 'u-9', status: 'SUSPENDED' }))
      }),
    )
    const { user } = renderApp('/admin/users')
    await user.click(await screen.findByRole('button', { name: 'Actions for Dana Doe' }))
    await user.click(await screen.findByRole('menuitem', { name: /deactivate/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/signed out everywhere/i)).toBeInTheDocument()
    expect(bodies).toHaveLength(0) // nothing sent before confirming
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }))
    expect(
      await within(dialog).findByText(/cannot suspend or change the role of your own account/i),
    ).toBeInTheDocument()
    fail = false
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(bodies).toEqual([{ status: 'SUSPENDED' }, { status: 'SUSPENDED' }])
    expect(await screen.findByText(/Dana Doe was deactivated/)).toBeInTheDocument()
  })

  it('offers no actions on the administrator’s own row', async () => {
    const me = signInAs('ADMIN')
    mockCompanies()
    server.use(
      http.get(`${API}/users`, () =>
        HttpResponse.json(
          page([
            makeAdminUser({
              id: me.id,
              first_name: 'Riley',
              last_name: 'Admin',
              role: 'ADMIN',
              email: me.email,
            }),
          ]),
        ),
      ),
    )
    renderApp('/admin/users')
    expect(await screen.findByText('(you)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
  })

  it('changes a role; staff roles require a company', async () => {
    signInAs('ADMIN')
    mockCompanies()
    const bodies: unknown[] = []
    server.use(
      http.get(`${API}/users`, () =>
        HttpResponse.json(page([makeAdminUser({ id: 'u-9', first_name: 'Dana', last_name: 'Doe' })])),
      ),
      http.patch(`${API}/users/u-9`, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(makeAdminUser({ id: 'u-9', role: 'RECRUITER', company_id: 'c-2' }))
      }),
    )
    const { user } = renderApp('/admin/users')
    await user.click(await screen.findByRole('button', { name: 'Actions for Dana Doe' }))
    await user.click(await screen.findByRole('menuitem', { name: /change role/i }))
    const dialog = await screen.findByRole('dialog', { name: 'Change role' })
    const save = within(dialog).getByRole('button', { name: 'Save role' })
    expect(save).toBeDisabled() // unchanged
    await user.click(within(dialog).getByRole('combobox', { name: /^role/i }))
    await user.click(await screen.findByRole('option', { name: 'Recruiter' }))
    expect(save).toBeDisabled() // company still missing
    await user.click(await within(dialog).findByRole('combobox', { name: /company/i }))
    await user.click(await screen.findByRole('option', { name: 'Orbit Finance' }))
    await user.click(save)
    await waitFor(() => expect(bodies).toEqual([{ role: 'RECRUITER', company_id: 'c-2' }]))
  })

  it('creates a user, mapping a duplicate-email error onto the field', async () => {
    signInAs('ADMIN')
    mockCompanies()
    let attempts = 0
    let body: Record<string, unknown> = {}
    server.use(
      http.get(`${API}/users`, () => HttpResponse.json(page([makeAdminUser()]))),
      http.post(`${API}/users`, async ({ request }) => {
        attempts += 1
        body = (await request.json()) as Record<string, unknown>
        return attempts === 1
          ? HttpResponse.json(
              errorBody('EMAIL_ALREADY_REGISTERED', 'An account with this email already exists'),
              { status: 409 },
            )
          : HttpResponse.json(
              makeAdminUser({ id: 'u-new', first_name: 'Nia', last_name: 'New', role: 'CANDIDATE' }),
              { status: 201 },
            )
      }),
    )
    const { user } = renderApp('/admin/users')
    await user.click(await screen.findByRole('button', { name: 'Create user' }))
    const dialog = await screen.findByRole('dialog', { name: 'Create user' })
    await user.click(within(dialog).getByRole('combobox', { name: /^role/i }))
    await user.click(await screen.findByRole('option', { name: 'Candidate' }))
    expect(within(dialog).queryByText('Company')).not.toBeInTheDocument()
    await user.type(within(dialog).getByLabelText(/first name/i), 'Nia')
    await user.type(within(dialog).getByLabelText(/last name/i), 'New')
    await user.type(within(dialog).getByLabelText(/^email/i), 'nia@example.com')
    await user.type(within(dialog).getByLabelText(/initial password/i, { selector: 'input' }), 'short')
    await user.click(within(dialog).getByRole('button', { name: 'Create user' }))
    expect(await within(dialog).findByText('Use at least 10 characters')).toBeInTheDocument()
    expect(attempts).toBe(0)
    await user.clear(within(dialog).getByLabelText(/initial password/i, { selector: 'input' }))
    await user.type(
      within(dialog).getByLabelText(/initial password/i, { selector: 'input' }),
      'GoodPass12345',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Create user' }))
    expect(await within(dialog).findByText('An account with this email already exists')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Create user' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Create user' })).not.toBeInTheDocument())
    expect(body).toMatchObject({ email: 'nia@example.com', role: 'CANDIDATE', company_id: null, phone: null })
  })

  it('shows an empty state, a filtered empty state and a retryable error', async () => {
    signInAs('ADMIN')
    mockCompanies()
    let failing = true
    server.use(
      http.get(`${API}/users`, ({ request }) => {
        if (failing) return HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
        return HttpResponse.json(page([]))
        void request
      }),
    )
    const { user } = renderApp('/admin/users')
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    failing = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByText('No users yet')).toBeInTheDocument()
  })

  it('shows "no results" when filters match nothing', async () => {
    signInAs('ADMIN')
    mockCompanies()
    server.use(http.get(`${API}/users`, () => HttpResponse.json(page([]))))
    renderApp('/admin/users?role=ADMIN')
    expect(await screen.findByText('No users match these filters')).toBeInTheDocument()
  })

  it('is not available to recruiters', async () => {
    signInAs('RECRUITER')
    renderApp('/admin/users')
    expect(await screen.findByText(/don.t have access to this page/i)).toBeInTheDocument()
  })
})
