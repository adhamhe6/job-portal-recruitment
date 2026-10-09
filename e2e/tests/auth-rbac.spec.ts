import { expect, test } from '@playwright/test'
import { ACCOUNTS, login } from './helpers'

test.describe('authentication and role-based access', () => {
  test('bad credentials are rejected with a clear message and no session', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('textbox', { name: 'Email' }).fill(ACCOUNTS.candidate)
    await page.getByRole('textbox', { name: 'Password' }).fill('definitely-wrong')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('a candidate signs in, sees the candidate area, and cannot reach staff or admin pages', async ({ page }) => {
    await login(page, ACCOUNTS.candidate)
    await expect(page).toHaveURL(/\/dashboard/)
    for (const path of ['/admin/system', '/manage/jobs', '/candidates']) {
      await page.goto(path)
      await expect(page.getByText(/don.t have access to this page/i).first()).toBeVisible()
    }
  })

  test('a recruiter cannot reach admin pages; the admin can', async ({ page }) => {
    await login(page, ACCOUNTS.recruiter)
    await page.goto('/admin/system')
    await expect(page.getByText(/don.t have access to this page/i).first()).toBeVisible()
    await page.context().clearCookies()
    await page.evaluate(() => sessionStorage.clear())
    await login(page, ACCOUNTS.admin)
    await page.goto('/admin/system')
    await expect(page.getByRole('heading', { name: /system|monitoring/i }).first()).toBeVisible()
  })

  test('the session survives a reload (refresh cookie) and ends on sign out', async ({ page }) => {
    await login(page, ACCOUNTS.candidate)
    await page.reload()
    await expect(page).toHaveURL(/\/dashboard/)
    await page.getByRole('button', { name: /account|profile|menu|alex/i }).first().click()
    await page.getByRole('menuitem', { name: /sign out|log out/i }).click()
    await expect(page).toHaveURL(/\/login|\/$/)
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login/)
  })
})
