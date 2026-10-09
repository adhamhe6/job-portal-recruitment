import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeCompany, makeMember } from '@/features/admin/__tests__/fixtures'
import { COMPANY_ID, errorBody } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const API = '/api/v1'
const company = makeCompany({ id: COMPANY_ID })

describe('company settings', () => {
  it('lets a company administrator edit the profile (PATCH with explicit nulls for cleared fields)', async () => {
    signInAs('RECRUITER') // is_company_admin: true
    let body: Record<string, unknown> | null = null
    server.use(
      http.get(`${API}/companies/me`, () => HttpResponse.json(company)),
      http.patch(`${API}/companies/${COMPANY_ID}`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          ...company,
          name: 'Northwind Systems',
          industry: null,
          website: 'https://nw.example.org',
          updated_at: '2026-10-09T00:00:00Z',
        })
      }),
    )
    const { user } = renderApp('/settings/company')
    const name = await screen.findByLabelText(/company name/i)
    expect(name).toHaveValue('Northwind Labs')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
    await user.clear(name)
    await user.type(name, 'Northwind Systems')
    await user.clear(screen.getByLabelText(/^industry/i))
    await user.clear(screen.getByLabelText(/^website/i))
    await user.type(screen.getByLabelText(/^website/i), 'nw.example.org')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({
      name: 'Northwind Systems',
      industry: null,
      website: 'https://nw.example.org',
      size: '51-200',
      logo_url: null,
    })
    expect(await screen.findByText('Company profile saved')).toBeInTheDocument()
  })

  it('validates fields and maps a duplicate name from the server', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get(`${API}/companies/me`, () => HttpResponse.json(company)),
      http.patch(`${API}/companies/${COMPANY_ID}`, () =>
        HttpResponse.json(errorBody('COMPANY_NAME_TAKEN', 'A company with this name already exists'), {
          status: 409,
        }),
      ),
    )
    const { user } = renderApp('/settings/company')
    const name = await screen.findByLabelText(/company name/i)
    await user.clear(name)
    await user.type(name, 'N')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText(/at least 2 characters/i)).toBeInTheDocument()
    await user.type(name, 'orthwind Systems')
    await user.type(screen.getByLabelText(/^website/i), 'not a url')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText(/valid website address/i)).toBeInTheDocument()
    await user.clear(screen.getByLabelText(/^website/i))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('A company with this name already exists')).toBeInTheDocument()
  })

  it('is read-only for a recruiter who is not a company administrator', async () => {
    signInAs('RECRUITER', { is_company_admin: false })
    server.use(http.get(`${API}/companies/me`, () => HttpResponse.json(company)))
    renderApp('/settings/company')
    const name = await screen.findByLabelText(/company name/i)
    expect(name).toBeDisabled()
    expect(screen.getByText('View only')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument()
  })

  it('hiring managers cannot open the page at all', async () => {
    signInAs('HIRING_MANAGER')
    renderApp('/settings/company')
    expect(await screen.findByText(/don.t have access to this page/i)).toBeInTheDocument()
  })

  it('shows an error with retry and a suspended notice', async () => {
    signInAs('RECRUITER')
    let failing = true
    server.use(
      http.get(`${API}/companies/me`, () =>
        failing
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 })
          : HttpResponse.json({ ...company, status: 'SUSPENDED' }),
      ),
    )
    const { user } = renderApp('/settings/company')
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    failing = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByText(/company is suspended/i)).toBeInTheDocument()
  })

  it('tells a platform administrator without a company where to manage companies', async () => {
    signInAs('ADMIN')
    renderApp('/settings/company')
    expect(await screen.findByText('Your account is not attached to a company')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Manage companies' })).toHaveAttribute('href', '/admin/companies')
  })
})

describe('team settings', () => {
  const me = makeMember({
    id: 'user-recruiter',
    first_name: 'Riley',
    last_name: 'Recruiter',
    is_company_admin: true,
  })
  const hana = makeMember({
    id: 'm-2',
    first_name: 'Hana',
    last_name: 'Manager',
    role: 'HIRING_MANAGER',
    email: 'hana@x.example',
    job_title: null,
    department: null,
  })
  const gone = makeMember({
    id: 'm-3',
    first_name: 'Gus',
    last_name: 'Gone',
    status: 'SUSPENDED',
    email: 'gus@x.example',
  })

  it('lists members and exposes no actions on your own row', async () => {
    signInAs('RECRUITER')
    server.use(http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([me, hana, gone])))
    renderApp('/settings/team')
    const table = await screen.findByRole('table', { name: 'Team members' })
    expect(within(table).getByText('Hana Manager')).toBeInTheDocument()
    expect(within(table).getByText('(you)')).toBeInTheDocument()
    expect(within(table).getAllByText('Company admin')).toHaveLength(1)
    expect(within(table).getByText('Suspended')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Actions for Riley Recruiter' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Actions for Hana Manager' })).toBeInTheDocument()
  })

  it('adds a member, mapping duplicate e-mail to the field', async () => {
    signInAs('RECRUITER')
    let attempts = 0
    let body: Record<string, unknown> = {}
    server.use(
      http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([me])),
      http.post(`${API}/companies/${COMPANY_ID}/members`, async ({ request }) => {
        attempts += 1
        body = (await request.json()) as Record<string, unknown>
        return attempts === 1
          ? HttpResponse.json(
              errorBody('EMAIL_ALREADY_REGISTERED', 'An account with this email already exists'),
              { status: 409 },
            )
          : HttpResponse.json(
              makeMember({ id: 'm-9', first_name: 'Nia', last_name: 'New', role: 'HIRING_MANAGER' }),
              { status: 201 },
            )
      }),
    )
    const { user } = renderApp('/settings/team')
    await user.click(await screen.findByRole('button', { name: 'Add member' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add team member' })
    await user.type(within(dialog).getByLabelText(/first name/i), 'Nia')
    await user.type(within(dialog).getByLabelText(/last name/i), 'New')
    await user.type(within(dialog).getByLabelText(/work email/i), 'nia@x.example')
    await user.click(within(dialog).getByRole('combobox', { name: /^role/i }))
    await user.click(await screen.findByRole('option', { name: 'Hiring manager' }))
    await user.type(
      within(dialog).getByLabelText(/initial password/i, { selector: 'input' }),
      'GoodPass12345',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Add member' }))
    expect(await within(dialog).findByText('An account with this email already exists')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Add member' }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Add team member' })).not.toBeInTheDocument(),
    )
    expect(body).toMatchObject({
      email: 'nia@x.example',
      role: 'HIRING_MANAGER',
      phone: null,
      job_title: null,
    })
  })

  it('changes a member’s role', async () => {
    signInAs('RECRUITER')
    let body: unknown
    server.use(
      http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([me, hana])),
      http.patch(`${API}/companies/${COMPANY_ID}/members/m-2`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ ...hana, role: 'RECRUITER' })
      }),
    )
    const { user } = renderApp('/settings/team')
    await user.click(await screen.findByRole('button', { name: 'Actions for Hana Manager' }))
    await user.click(await screen.findByRole('menuitem', { name: /edit role/i }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Hana Manager' })
    await user.click(within(dialog).getByRole('combobox', { name: /^role/i }))
    await user.click(await screen.findByRole('option', { name: 'Recruiter' }))
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(body).toEqual({ role: 'RECRUITER', job_title: '', department: '' }))
  })

  it('deactivates only after confirmation and surfaces failures inside the dialog', async () => {
    signInAs('RECRUITER')
    const bodies: unknown[] = []
    let fail = true
    server.use(
      http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([me, hana])),
      http.patch(`${API}/companies/${COMPANY_ID}/members/m-2`, async ({ request }) => {
        bodies.push(await request.json())
        return fail
          ? HttpResponse.json(errorBody('FORBIDDEN', 'Only company administrators can do this'), {
              status: 403,
            })
          : HttpResponse.json({ ...hana, status: 'SUSPENDED' })
      }),
    )
    const { user } = renderApp('/settings/team')
    await user.click(await screen.findByRole('button', { name: 'Actions for Hana Manager' }))
    await user.click(await screen.findByRole('menuitem', { name: /deactivate/i }))
    const dialog = await screen.findByRole('alertdialog')
    expect(bodies).toHaveLength(0)
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }))
    expect(
      await within(dialog).findByText(/only company administrators can change the team/i),
    ).toBeInTheDocument()
    fail = false
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(bodies).toEqual([{ status: 'SUSPENDED' }, { status: 'SUSPENDED' }])
  })

  it('is view-only for a recruiter who is not a company administrator', async () => {
    signInAs('RECRUITER', { is_company_admin: false })
    server.use(http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([me, hana])))
    renderApp('/settings/team')
    expect(await screen.findByRole('table', { name: 'Team members' })).toBeInTheDocument()
    expect(screen.getByText('View only')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add member' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
  })

  it('shows loading failure with retry and an empty state', async () => {
    signInAs('RECRUITER')
    let failing = true
    server.use(
      http.get(`${API}/companies/${COMPANY_ID}/members`, () =>
        failing
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 })
          : HttpResponse.json([]),
      ),
    )
    const { user } = renderApp('/settings/team')
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    failing = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByText('No team members yet')).toBeInTheDocument()
  })

  it('hiring managers cannot open the page', async () => {
    signInAs('HIRING_MANAGER')
    renderApp('/settings/team')
    expect(await screen.findByText(/don.t have access to this page/i)).toBeInTheDocument()
  })
})
