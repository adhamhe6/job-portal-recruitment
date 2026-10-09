import { expect, type Page, type APIRequestContext } from '@playwright/test'

export const PASSWORD = 'DemoPass123!'
export const ACCOUNTS = {
  candidate: 'candidate@demo.example',
  recruiter: 'recruiter@demo.example',
  admin: 'admin@demo.example',
} as const

export async function login(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Email' }).fill(email)
  await page.getByRole('textbox', { name: 'Password' }).fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).not.toHaveURL(/\/login/)
}

/** API login for setup/verification that is not the point of the scenario under test. */
export async function apiToken(request: APIRequestContext, email: string): Promise<string> {
  const res = await request.post('/api/v1/auth/login', { data: { email, password: PASSWORD } })
  expect(res.ok(), await res.text()).toBeTruthy()
  return (await res.json()).access_token as string
}

export const bearer = (token: string) => ({ Authorization: `Bearer ${token}` })

export function uniqueSuffix(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}

/** A brand-new candidate account (API-created so the scenario under test starts from a clean slate). */
export async function newCandidate(request: APIRequestContext): Promise<{ email: string; first: string }> {
  const email = `e2e.${uniqueSuffix()}@example.com`
  const first = 'Eve'
  const res = await request.post('/api/v1/auth/register', {
    data: { email, password: PASSWORD, first_name: first, last_name: 'Tester', role: 'CANDIDATE' },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  return { email, first }
}
