import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeCompletion, makeProfile } from '@/test/candidateFixtures'
import { errorBody, skill } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const API = '/api/v1'
const withProfile = (profile = makeProfile()) =>
  server.use(http.get(`${API}/candidates/me`, () => HttpResponse.json(profile)))

describe('ProfilePage', () => {
  it('shows the profile sections and the completeness meter with links to what is missing', async () => {
    signInAs('CANDIDATE')
    withProfile()
    renderApp('/profile')
    expect(await screen.findByRole('heading', { level: 1, name: 'My profile' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Headline')).toHaveValue('Backend engineer')
    const meter = screen.getByRole('progressbar', { name: 'Profile completeness' })
    expect(meter).toHaveAttribute('aria-valuenow', '70')
    expect(screen.getByRole('link', { name: /Upload your résumé/ })).toHaveAttribute('href', '/resume')
    expect(screen.getByText('Senior Engineer')).toBeInTheDocument()
    expect(screen.getByText('TU Berlin')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Languages' })).toHaveTextContent('English')
  })

  it('shows an error with retry when the profile cannot be loaded', async () => {
    signInAs('CANDIDATE')
    let calls = 0
    server.use(
      http.get(`${API}/candidates/me`, () => {
        calls++
        return calls === 1
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(makeProfile())
      }),
    )
    const { user } = renderApp('/profile')
    expect(await screen.findByRole('heading', { name: "Couldn't load your profile" })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByLabelText('Headline')).toBeInTheDocument()
  })

  it('validates inline and saves the basics with PATCH (empty strings become null)', async () => {
    signInAs('CANDIDATE')
    withProfile()
    let body: Record<string, unknown> | null = null
    server.use(
      http.patch(`${API}/candidates/me`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(makeProfile({ headline: 'Staff engineer' }))
      }),
    )
    const { user } = renderApp('/profile')
    const headline = await screen.findByLabelText('Headline')

    // client-side validation: bad years of experience
    const years = screen.getByLabelText('Years of experience', { selector: 'input' })
    await user.clear(years)
    await user.type(years, 'abc')
    await user.tab()
    expect(await screen.findByText('Years of experience must be a number')).toBeInTheDocument()
    await user.clear(years)
    await user.type(years, '7')

    await user.clear(headline)
    await user.type(headline, 'Staff engineer')
    await user.clear(screen.getByLabelText('Phone'))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({
      headline: 'Staff engineer',
      years_experience: '7',
      phone: null,
      linkedin_url: null,
      remote_preference: 'HYBRID',
      is_searchable: true,
    })
    expect(await screen.findByText('Profile saved')).toBeInTheDocument()
  })

  it('maps a server validation error onto the field', async () => {
    signInAs('CANDIDATE')
    withProfile()
    server.use(
      http.patch(`${API}/candidates/me`, () =>
        HttpResponse.json(
          errorBody('VALIDATION_ERROR', 'Invalid', [
            { field: 'phone', message: 'Value error, bad phone', type: 'value_error' },
          ]),
          { status: 422 },
        ),
      ),
    )
    const { user } = renderApp('/profile')
    const headline = await screen.findByLabelText('Headline')
    await user.type(headline, ' II')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('bad phone')).toBeInTheDocument()
  })

  it('adds an experience: required fields are enforced, then the payload is posted', async () => {
    signInAs('CANDIDATE')
    withProfile()
    let body: Record<string, unknown> | null = null
    server.use(
      http.post(`${API}/candidates/me/experiences`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'exp-2', source: 'USER', ...body }, { status: 201 })
      }),
    )
    const { user } = renderApp('/profile')
    await user.click(await screen.findByRole('button', { name: 'Add experience' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add experience' })

    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await within(dialog).findByText('Job title is required')).toBeInTheDocument()
    expect(within(dialog).getByText('Company is required')).toBeInTheDocument()
    expect(within(dialog).getByText('Start date is required')).toBeInTheDocument()

    await user.type(within(dialog).getByLabelText(/Job title/), 'Tech Lead')
    await user.type(within(dialog).getByLabelText(/Company/), 'Globex')
    await user.type(within(dialog).getByLabelText(/Start date/), '2019-02-01')
    await user.click(within(dialog).getByLabelText('I currently work here'))
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({
      title: 'Tech Lead',
      company_name: 'Globex',
      start_date: '2019-02-01',
      end_date: null,
      is_current: true,
      location: null,
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('rejects an end date before the start date', async () => {
    signInAs('CANDIDATE')
    withProfile()
    const { user } = renderApp('/profile')
    await user.click(await screen.findByRole('button', { name: 'Edit Senior Engineer at Acme' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit experience' })
    await user.click(within(dialog).getByLabelText('I currently work here'))
    await user.type(within(dialog).getByLabelText(/End date/), '2020-01-01')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await within(dialog).findByText('End date must not be before the start date')).toBeInTheDocument()
  })

  it('deletes an education entry after confirmation', async () => {
    signInAs('CANDIDATE')
    withProfile()
    let deleted = ''
    server.use(
      http.delete(`${API}/candidates/me/educations/:id`, ({ params }) => {
        deleted = String(params.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { user } = renderApp('/profile')
    await user.click(await screen.findByRole('button', { name: 'Delete TU Berlin' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('TU Berlin will be removed')
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(deleted).toBe('edu-1'))
  })

  it('edits a language by adding the new row before removing the old one', async () => {
    signInAs('CANDIDATE')
    withProfile()
    const calls: string[] = []
    server.use(
      http.post(`${API}/candidates/me/languages`, async ({ request }) => {
        calls.push(`POST ${JSON.stringify(await request.json())}`)
        return HttpResponse.json(
          { id: 'lang-2', language: 'English', proficiency: 'NATIVE' },
          { status: 201 },
        )
      }),
      http.delete(`${API}/candidates/me/languages/:id`, ({ params }) => {
        calls.push(`DELETE ${String(params.id)}`)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { user } = renderApp('/profile')
    await user.click(await screen.findByRole('button', { name: 'Edit English' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit language' })
    await user.selectOptions(within(dialog).getByLabelText(/Proficiency/), 'NATIVE')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[0]).toBe('POST {"language":"English","proficiency":"NATIVE"}')
    expect(calls[1]).toBe('DELETE lang-1')
  })

  it('adds a skill from the autocomplete with proficiency and years', async () => {
    signInAs('CANDIDATE')
    withProfile()
    let body: Record<string, unknown> | null = null
    server.use(
      http.post(`${API}/candidates/me/skills`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          {
            id: 'cs-2',
            skill: skill('Kubernetes'),
            proficiency: 'ADVANCED',
            years_experience: '2.5',
            source: 'USER',
            status: 'CONFIRMED',
            confidence: null,
          },
          { status: 201 },
        )
      }),
    )
    const { user } = renderApp('/profile')
    await user.click(await screen.findByRole('combobox', { name: 'Add a skill' }))
    await user.type(await screen.findByPlaceholderText('Type a skill name…'), 'kube')
    await user.click(await screen.findByRole('option', { name: /Kubernetes/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Add Kubernetes' })
    await user.selectOptions(within(dialog).getByLabelText(/Proficiency/), 'ADVANCED')
    await user.type(within(dialog).getByLabelText(/Years of experience/), '2.5')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({ skill_id: 'skill-kubernetes', proficiency: 'ADVANCED', years_experience: '2.5' })
  })

  it('lets the candidate confirm or dismiss résumé-suggested skills', async () => {
    signInAs('CANDIDATE')
    const base = makeProfile()
    withProfile(
      makeProfile({
        skills: [
          ...base.skills,
          {
            id: 'cs-9',
            skill: skill('Terraform'),
            proficiency: null,
            years_experience: null,
            source: 'RESUME',
            status: 'SUGGESTED',
            confidence: 0.8,
          },
        ],
      }),
    )
    let patched: { id: string; body: unknown } | null = null
    server.use(
      http.patch(`${API}/candidates/me/skills/:id`, async ({ params, request }) => {
        patched = { id: String(params.id), body: await request.json() }
        return HttpResponse.json({})
      }),
    )
    const { user } = renderApp('/profile')
    expect(await screen.findByText('Suggested from your résumé')).toBeInTheDocument()
    // suggestions are not part of the confirmed list
    expect(
      within(screen.getByRole('list', { name: 'Your skills' })).queryByText('Terraform'),
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Confirm Terraform' }))
    await waitFor(() => expect(patched).toEqual({ id: 'cs-9', body: { status: 'CONFIRMED' } }))
  })

  it('shows 100% as complete when nothing is missing', async () => {
    signInAs('CANDIDATE')
    withProfile(
      makeProfile({
        completion: makeCompletion({
          percent: 100,
          items: [{ key: 'headline', label: 'Add a professional headline', weight: 10, done: true }],
          missing: [],
        }),
      }),
    )
    renderApp('/profile')
    expect(await screen.findByRole('progressbar', { name: 'Profile completeness' })).toHaveAttribute(
      'aria-valuenow',
      '100',
    )
  })
})
