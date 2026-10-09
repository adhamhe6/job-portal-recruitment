import { expect, test } from '@playwright/test'
import { login, newCandidate } from './helpers'

test.describe('workflow 1 · a candidate finds a job, applies, and tracks the application', () => {
  test('search → job detail → apply → appears in My applications → withdraw', async ({ page, request }) => {
    const { email } = await newCandidate(request)
    await login(page, email)

    // search narrows the catalogue and shows real results
    await page.goto('/jobs')
    await page.getByPlaceholder('Search by title, skill or keyword').fill('senior backend engineer')
    await expect(page.getByRole('status').filter({ hasText: /jobs? found/ })).toBeVisible()
    const result = page.getByRole('link', { name: 'Senior Backend Engineer', exact: true })
    await expect(result).toBeVisible()
    await result.click()

    // job detail → apply with a cover letter
    await expect(page.getByRole('heading', { level: 1, name: 'Senior Backend Engineer' })).toBeVisible()
    await page.getByRole('button', { name: 'Apply now' }).first().click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Cover letter').fill('I build FastAPI services on PostgreSQL and would love to join the platform team.')
    await dialog.getByRole('button', { name: 'Submit application' }).click()
    await expect(page.getByText(/you applied/i).first()).toBeVisible()

    // applying twice is impossible
    await expect(page.getByRole('button', { name: 'Apply now' })).toHaveCount(0)

    // the application is listed with its status, and can be withdrawn with confirmation
    await page.goto('/applications')
    await expect(page.getByText('Senior Backend Engineer').first()).toBeVisible()
    await expect(page.getByText(/applied/i).first()).toBeVisible()
    await page.getByRole('button', { name: /withdraw/i }).first().click()
    await page.getByRole('alertdialog').getByRole('button', { name: /withdraw/i }).click()
    await expect(page.getByText(/withdrawn/i).first()).toBeVisible()
  })
})
