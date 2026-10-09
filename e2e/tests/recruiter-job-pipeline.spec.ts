import { expect, test } from '@playwright/test'
import { ACCOUNTS, login, newCandidate, uniqueSuffix } from './helpers'

test.describe('workflows 2–3 · a recruiter publishes a job and works the applicant through the pipeline', () => {
  test('create → publish → candidate applies → recruiter moves them forward and the history shows it', async ({
    browser,
    page,
    request,
  }) => {
    const title = `E2E Platform Engineer ${uniqueSuffix()}`

    // --- recruiter creates and publishes a job
    await login(page, ACCOUNTS.recruiter)
    await page.goto('/manage/jobs/new')
    await page.getByLabel('Job title').fill(title)
    await page.getByLabel('Location').fill('Berlin, Germany')
    await page.getByLabel('Workplace').selectOption('Hybrid')
    await page.getByLabel('Employment type').selectOption('Full-time')
    await page
      .getByLabel('About the role')
      .fill(
        'Build and operate the internal platform: Python services, PostgreSQL, Redis and CI/CD pipelines.',
      )
    await page.getByLabel('Min. experience (years)').fill('2')
    await page.getByRole('combobox', { name: 'Skills' }).click()
    const picker = page.getByRole('dialog')
    await picker.getByRole('combobox', { name: 'Skills' }).fill('Python')
    await picker
      .getByRole('option', { name: /^Python\b/ })
      .first()
      .click()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Publish' }).click()
    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/) // lands on the published posting
    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()

    // --- it is publicly searchable
    const publicPage = await (await browser.newContext({ baseURL: page.url().split('/manage')[0] })).newPage()
    await publicPage.goto('/jobs')
    await publicPage.getByPlaceholder('Search by title, skill or keyword').fill(title)
    await expect(publicPage.getByRole('link', { name: title, exact: true })).toBeVisible()
    await publicPage.context().close()

    // --- a new candidate applies
    const { email } = await newCandidate(request)
    const candCtx = await browser.newContext({
      baseURL: page.url().split('/manage')[0],
    })
    const cand = await candCtx.newPage()
    await login(cand, email)
    await cand.goto('/jobs')
    await cand.getByPlaceholder('Search by title, skill or keyword').fill(title)
    await cand.getByRole('link', { name: title, exact: true }).click()
    await cand.getByRole('button', { name: 'Apply now' }).first().click()
    await cand.getByRole('dialog').getByRole('button', { name: 'Submit application' }).click()
    await expect(cand.getByText(/you applied/i).first()).toBeVisible()
    await candCtx.close()

    // --- recruiter sees the applicant in the pipeline and moves them to Screening
    await page.goto('/applications')
    await page.getByRole('searchbox').fill('Tester')
    const card = page.getByText('Eve Tester').first()
    await expect(card).toBeVisible()
    await page
      .getByRole('button', { name: /Move Eve Tester/ })
      .first()
      .click()
    await page.getByRole('menuitem', { name: /screening/i }).click()

    // --- the detail page records the transition in the audited history
    await page
      .getByRole('link', { name: /Eve Tester/ })
      .first()
      .click()
    await expect(page.getByText(/screening/i).first()).toBeVisible()
    await expect(page.getByText(/history|timeline/i).first()).toBeVisible()
    await page.getByLabel(/note/i).first().fill('Strong match on the platform skills.')
    await page.getByRole('button', { name: /add note/i }).click()
    await expect(page.getByText('Strong match on the platform skills.')).toBeVisible()
  })
})
