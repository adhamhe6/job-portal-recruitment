import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, login } from './helpers'

test.use({ viewport: { width: 375, height: 800 } })

async function noHorizontalScroll(page: Page, path: string) {
  await page.goto(path)
  await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
  await page.waitForLoadState('networkidle')
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow, `${path} scrolls horizontally by ${overflow}px at 375px`).toBeLessThanOrEqual(1)
}

test.describe('responsive layout at phone width (375px)', () => {
  test('public and candidate pages fit the screen', async ({ page }) => {
    await noHorizontalScroll(page, '/jobs')
    await noHorizontalScroll(page, '/login')
    await login(page, ACCOUNTS.candidate)
    for (const path of [
      '/dashboard',
      '/jobs',
      '/applications',
      '/resume',
      '/profile',
      '/recommended',
      '/interviews',
    ]) {
      await noHorizontalScroll(page, path)
    }
  })

  test('recruiter pages fit the screen and navigation stays reachable', async ({ page }) => {
    await login(page, ACCOUNTS.recruiter)
    for (const path of [
      '/dashboard',
      '/applications',
      '/candidates',
      '/interviews',
      '/manage/jobs',
      '/reports',
    ]) {
      await noHorizontalScroll(page, path)
    }
    await page.goto('/dashboard')
    await page
      .getByRole('button', { name: /open (main )?(menu|navigation)|menu/i })
      .first()
      .click()
    await expect(
      page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Applications' }),
    ).toBeVisible()
  })
})
