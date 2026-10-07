import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { tokenStore } from '@/lib/api'
import { errorBody, makeUser, tokenFor } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs, waitForBoot } from '@/test/test-utils'

const fillLogin = async (user: ReturnType<typeof renderApp>['user'], email: string, password: string) => {
  await user.type(await screen.findByLabelText(/^email/i), email)
  await user.type(screen.getByLabelText(/^password/i, { selector: 'input' }), password)
}

describe('login', () => {
  it('signs in, keeps the token in memory, and lands on the dashboard', async () => {
    const candidate = makeUser('CANDIDATE')
    let authHeader: string | null = null
    server.use(
      http.post('/api/v1/auth/login', async ({ request }) => {
        expect(await request.json()).toEqual({ email: 'alex@example.com', password: 'DemoPass123!' })
        return HttpResponse.json(tokenFor(candidate, 'tok-login'))
      }),
      http.get('/api/v1/notifications/unread-count', ({ request }) => {
        authHeader = request.headers.get('authorization')
        return HttpResponse.json({ unread: 0 })
      }),
    )
    const { user, router } = renderApp('/login')
    await fillLogin(user, 'alex@example.com', 'DemoPass123!')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/dashboard'))
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(tokenStore.get()).toBe('tok-login')
    await waitFor(() => expect(authHeader).toBe('Bearer tok-login'))
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain('tok-login')
  })

  it('returns to the page the user was heading to (?next=)', async () => {
    server.use(http.post('/api/v1/auth/login', () => HttpResponse.json(tokenFor(makeUser('CANDIDATE')))))
    const { user, router } = renderApp('/login?next=%2Fnotifications')
    await fillLogin(user, 'alex@example.com', 'DemoPass123!')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/notifications'))
  })

  it('ignores external ?next= targets', async () => {
    server.use(http.post('/api/v1/auth/login', () => HttpResponse.json(tokenFor(makeUser('CANDIDATE')))))
    const { user, router } = renderApp('/login?next=%2F%2Fevil.example.com')
    await fillLogin(user, 'alex@example.com', 'DemoPass123!')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/dashboard'))
  })

  it('shows a clear message for wrong credentials and stays on the page', async () => {
    server.use(
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json(errorBody('INVALID_CREDENTIALS', 'Invalid email or password'), { status: 401 }),
      ),
    )
    const { user, router } = renderApp('/login')
    await fillLogin(user, 'alex@example.com', 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText(/incorrect email or password/i)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
    expect(tokenStore.get()).toBeNull()
  })

  it('validates required fields before calling the API', async () => {
    const { user } = renderApp('/login')
    await user.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter your email address')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
  })

  it('offers demo accounts only when /meta says demo mode, and signs in with one click', async () => {
    const recruiter = makeUser('RECRUITER')
    let body: unknown
    server.use(
      http.get('/api/v1/meta', () =>
        HttpResponse.json({
          demo_mode: true,
          demo_password: 'DemoPass123!',
          demo_accounts: [
            { role: 'RECRUITER', label: 'Recruiter — Northwind Labs', email: 'recruiter@demo.example' },
          ],
        }),
      ),
      http.post('/api/v1/auth/login', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(tokenFor(recruiter))
      }),
    )
    const { user, router } = renderApp('/login')
    const demo = await screen.findByRole('region', { name: /demo account/i })
    await user.click(within(demo).getByRole('button', { name: /Recruiter — Northwind Labs/ }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/dashboard'))
    expect(body).toEqual({ email: 'recruiter@demo.example', password: 'DemoPass123!' })
  })

  it('hides demo accounts when /meta is absent (404) and the env flag is off', async () => {
    renderApp('/login')
    await screen.findByRole('heading', { name: 'Welcome back' })
    await waitFor(() => expect(screen.queryByText(/try a demo account/i)).not.toBeInTheDocument())
  })

  it('hides demo accounts when /meta reports demo_mode=false', async () => {
    server.use(http.get('/api/v1/meta', () => HttpResponse.json({ demo_mode: false, demo_accounts: [] })))
    renderApp('/login')
    await screen.findByRole('heading', { name: 'Welcome back' })
    expect(screen.queryByText(/try a demo account/i)).not.toBeInTheDocument()
  })
})

describe('session', () => {
  it('restores the session on page load through the silent refresh (no login screen)', async () => {
    const rec = signInAs('RECRUITER')
    renderApp('/dashboard')
    await waitForBoot()
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: new RegExp(`Account menu for ${rec.first_name}`) }),
    ).toBeInTheDocument()
    expect(tokenStore.get()).toBe('access-token-1')
  })

  it('shows a retryable error if the API is unreachable at boot', async () => {
    server.use(http.post('/api/v1/auth/refresh', () => HttpResponse.error()))
    renderApp('/dashboard')
    expect(await screen.findByRole('alert')).toHaveTextContent(/can't connect|cannot reach/i)
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('redirects anonymous visitors from protected pages to /login with the destination preserved', async () => {
    const { router } = renderApp('/applications?status=OFFER')
    await screen.findByRole('heading', { name: 'Welcome back' })
    expect(router.state.location.pathname).toBe('/login')
    expect(new URLSearchParams(router.state.location.search).get('next')).toBe('/applications?status=OFFER')
  })

  it('sends signed-in users away from /login', async () => {
    signInAs('CANDIDATE')
    const { router } = renderApp('/login')
    await waitFor(() => expect(router.state.location.pathname).toBe('/dashboard'))
  })

  it('logs out: revokes the session, clears the token and returns to /login', async () => {
    signInAs('CANDIDATE')
    let loggedOut = false
    server.use(
      http.post('/api/v1/auth/logout', () => {
        loggedOut = true
        return HttpResponse.json({ message: 'Signed out' })
      }),
    )
    const { user, router } = renderApp('/dashboard')
    await user.click(await screen.findByRole('button', { name: /Account menu for/ }))
    await user.click(await screen.findByRole('menuitem', { name: /sign out/i }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
    expect(loggedOut).toBe(true)
    expect(tokenStore.get()).toBeNull()
    expect(router.state.location.search).toBe('') // an explicit sign-out does not leave a ?next=
  })

  it('401 -> refresh -> retry keeps the user signed in', async () => {
    const candidate = makeUser('CANDIDATE')
    let refreshes = 0
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes++
        return HttpResponse.json(tokenFor(candidate, `tok-${refreshes}`))
      }),
      http.get('/api/v1/notifications', ({ request }) =>
        request.headers.get('authorization') === 'Bearer tok-2'
          ? HttpResponse.json({ items: [], page: 1, page_size: 15, total: 0, pages: 0 })
          : HttpResponse.json(errorBody('TOKEN_EXPIRED', 'Token has expired'), { status: 401 }),
      ),
    )
    const { router } = renderApp('/notifications')
    expect(await screen.findByText('No notifications yet')).toBeInTheDocument()
    expect(refreshes).toBe(2) // boot + one silent refresh after the 401
    expect(router.state.location.pathname).toBe('/notifications')
  })

  it('when the session cannot be refreshed, signs out and redirects to /login?next=', async () => {
    const candidate = makeUser('CANDIDATE')
    let refreshes = 0
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes++
        return refreshes === 1
          ? HttpResponse.json(tokenFor(candidate))
          : HttpResponse.json(errorBody('INVALID_REFRESH_TOKEN', 'expired'), { status: 401 })
      }),
      http.get('/api/v1/notifications', () =>
        HttpResponse.json(errorBody('TOKEN_EXPIRED', 'Token has expired'), { status: 401 }),
      ),
    )
    const { router } = renderApp('/notifications')
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
    expect(new URLSearchParams(router.state.location.search).get('next')).toBe('/notifications')
    expect(tokenStore.get()).toBeNull()
  })
})

describe('registration', () => {
  it('validates the password rules and confirmation on the client', async () => {
    const { user } = renderApp('/register')
    await user.type(await screen.findByLabelText(/^first name/i), 'Ada')
    await user.type(screen.getByLabelText(/^last name/i), 'Lovelace')
    await user.type(screen.getByLabelText(/^email/i), 'ada@example.com')
    await user.type(screen.getByLabelText(/^password/i, { selector: 'input' }), 'short')
    await user.type(screen.getByLabelText(/^confirm password/i, { selector: 'input' }), 'different1')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Use at least 10 characters')).toBeInTheDocument()
    expect(screen.getByText('Passwords do not match')).toBeInTheDocument()
  })

  it('maps EMAIL_ALREADY_REGISTERED onto the email field', async () => {
    server.use(
      http.post('/api/v1/auth/register', () =>
        HttpResponse.json(
          errorBody('EMAIL_ALREADY_REGISTERED', 'An account with this email already exists'),
          { status: 409 },
        ),
      ),
    )
    const { user } = renderApp('/register')
    await user.type(await screen.findByLabelText(/^first name/i), 'Ada')
    await user.type(screen.getByLabelText(/^last name/i), 'Lovelace')
    await user.type(screen.getByLabelText(/^email/i), 'ada@example.com')
    await user.type(screen.getByLabelText(/^password/i, { selector: 'input' }), 'CorrectHorse42')
    await user.type(screen.getByLabelText(/^confirm password/i, { selector: 'input' }), 'CorrectHorse42')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    const email = await screen.findByLabelText(/^email/i)
    await waitFor(() => expect(email).toHaveAttribute('aria-invalid', 'true'))
    expect(screen.getByText('An account with this email already exists')).toBeInTheDocument()
  })

  it('creates the account and signs in', async () => {
    const created = makeUser('CANDIDATE', { first_name: 'Ada', last_name: 'Lovelace' })
    let payload: unknown
    server.use(
      http.post('/api/v1/auth/register', async ({ request }) => {
        payload = await request.json()
        return HttpResponse.json(tokenFor(created), { status: 201 })
      }),
    )
    const { user, router } = renderApp('/register')
    await user.type(await screen.findByLabelText(/^first name/i), 'Ada')
    await user.type(screen.getByLabelText(/^last name/i), 'Lovelace')
    await user.type(screen.getByLabelText(/^email/i), 'ada@example.com')
    await user.type(screen.getByLabelText(/^password/i, { selector: 'input' }), 'CorrectHorse42')
    await user.type(screen.getByLabelText(/^confirm password/i, { selector: 'input' }), 'CorrectHorse42')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/dashboard'))
    expect(payload).toEqual({
      first_name: 'Ada',
      last_name: 'Lovelace',
      email: 'ada@example.com',
      password: 'CorrectHorse42',
      phone: null,
    })
  })

  it('employer registration maps COMPANY_NAME_TAKEN onto the company field and normalises the website', async () => {
    let payload: Record<string, unknown> = {}
    server.use(
      http.post('/api/v1/auth/register/employer', async ({ request }) => {
        payload = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(errorBody('COMPANY_NAME_TAKEN', 'A company with this name already exists'), {
          status: 409,
        })
      }),
    )
    const { user } = renderApp('/register/employer')
    await user.type(await screen.findByLabelText(/^first name/i), 'Rita')
    await user.type(screen.getByLabelText(/^last name/i), 'Recruiter')
    await user.type(screen.getByLabelText(/^work email/i), 'rita@acme.example')
    await user.type(screen.getByLabelText(/^password/i, { selector: 'input' }), 'CorrectHorse42')
    await user.type(screen.getByLabelText(/^confirm password/i, { selector: 'input' }), 'CorrectHorse42')
    await user.type(screen.getByLabelText(/^company name/i), 'Acme Robotics')
    await user.type(screen.getByLabelText(/^website/i), 'acme.example')
    await user.click(screen.getByRole('button', { name: 'Create company account' }))
    expect(await screen.findByText('A company with this name already exists')).toBeInTheDocument()
    expect(screen.getByLabelText(/^company name/i)).toHaveAttribute('aria-invalid', 'true')
    expect(payload).toMatchObject({
      company_name: 'Acme Robotics',
      company_website: 'https://acme.example',
      company_size: null,
    })
  })
})
