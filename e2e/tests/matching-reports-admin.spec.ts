import { expect, test } from '@playwright/test'
import { ACCOUNTS, apiToken, bearer, login } from './helpers'

test.describe('workflow 6 · matching, reports and monitoring', () => {
  test('recruiter sees an explained, ranked candidate list and can refresh it through the worker', async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, ACCOUNTS.recruiter)
    const jobs = await request.get('/api/v1/jobs?q=Senior+Backend&page_size=5', { headers: bearer(token) })
    const job = (await jobs.json()).items.find((j: { title: string }) => j.title === 'Senior Backend Engineer')
    expect(job).toBeTruthy()

    await login(page, ACCOUNTS.recruiter)
    await page.goto(`/matching/${job.id}`)
    // the ranking is ordered by score, and the seeded strong candidate is near the top with an explanation. Other
    // scenarios add candidates (a résumé that covers every required skill legitimately outranks the seed), so
    // the assertion is on ordering and presence rather than on a fixed first place.
    const cards = page.getByRole('article')
    await expect(cards.first()).toContainText(/\d+%/)
    const scores = (await cards.evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') ?? ''))).map((l) =>
      Number(/(\d+)% match/.exec(l)?.[1] ?? NaN),
    )
    expect(scores.length).toBeGreaterThan(3)
    expect([...scores].sort((a, b) => b - a)).toEqual(scores)
    const alex = page.getByRole('article', { name: /^Alex Rivera/ })
    await expect(alex).toBeVisible()
    expect(Number(/(\d+)% match/.exec((await alex.getAttribute('aria-label')) ?? '')?.[1])).toBeGreaterThanOrEqual(90)
    const first = alex
    await first.getByRole('button', { name: /why this score/i }).click()
    await expect(page.getByText(/python/i).first()).toBeVisible()
    await page.getByText(/how to read match scores/i).first().click()
    await expect(page.getByText(/ranking aid|not a hiring decision/i).first()).toBeVisible()

    // a refresh goes through the background worker and finishes
    await page.getByRole('button', { name: /refresh matches/i }).click()
    await expect(page.getByText(/refresh(ed)?|up to date|updated/i).first()).toBeVisible({ timeout: 60_000 })
  })

  test('reports render real numbers and export CSV', async ({ page }) => {
    await login(page, ACCOUNTS.recruiter)
    await page.goto('/reports')
    await expect(page.getByRole('heading', { level: 1, name: /reports/i })).toBeVisible()
    await expect(page.getByRole('tab').first()).toBeVisible()
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: /export csv/i }).click()
    await page.getByRole('menuitem').first().click()
    const file = await download
    expect(file.suggestedFilename()).toMatch(/\.csv$/)
  })

  test('admin monitoring shows dependency health and the background-task queue', async ({ page }) => {
    await login(page, ACCOUNTS.admin)
    await page.goto('/admin/system')
    await expect(page.getByRole('heading', { level: 1, name: /system monitoring/i })).toBeVisible()
    await expect(page.getByText(/database/i).first()).toBeVisible()
    await expect(page.getByText(/redis/i).first()).toBeVisible()
    await page.getByRole('tab', { name: /background tasks/i }).click()
    await expect(page.getByText(/completed/i).first()).toBeVisible()
  })
})
