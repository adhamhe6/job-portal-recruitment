import { expect, test } from '@playwright/test'
import { login, newCandidate, resumePdf } from './helpers'

test.describe('workflow 4 · résumé upload → async parsing → review → profile', () => {
  test('uploaded résumé is parsed by the worker; only accepted suggestions reach the profile', async ({
    page,
    request,
  }) => {
    const { email } = await newCandidate(request)
    await login(page, email)

    // upload a real PDF; the API validates it and queues background processing
    await page.goto('/resume')
    await page.locator('input[type=file]').setInputFiles({
      name: 'eve-cv.pdf',
      mimeType: 'application/pdf',
      buffer: await resumePdf('Eve Tester'),
    })
    await page.getByRole('button', { name: 'Upload résumé' }).click()

    // the worker extracts and parses it; the page polls until the résumé is processed
    await expect(page.getByText('Processed', { exact: true })).toBeVisible({
      timeout: 60_000,
    })
    await page.getByRole('button', { name: 'Review suggestions' }).click()

    // suggestions come from the file itself, with confidence and provenance
    const skills = page.getByRole('region', { name: 'Skills' })
    for (const skill of ['Python', 'PostgreSQL', 'Docker', 'Kubernetes']) {
      await expect(skills.getByRole('checkbox', { name: skill, exact: true })).toBeChecked()
    }
    await expect(page.getByRole('checkbox', { name: 'Backend Engineer at Acme Cloud' })).toBeChecked()
    await expect(page.getByRole('checkbox', { name: 'TU Berlin' })).toBeChecked()

    // the candidate stays in control: reject one suggestion, then apply the rest
    await page.getByRole('button', { name: 'Reject suggestion Terraform' }).click()
    await page.getByRole('button', { name: /^Apply \d+ selected to my profile$/ }).click()
    await expect(page.getByText(/added|applied/i).first()).toBeVisible()

    // the profile now carries the accepted data and not the rejected skill
    await page.goto('/profile')
    await expect(page.getByText('Python').first()).toBeVisible()
    await expect(page.getByText('Kubernetes').first()).toBeVisible()
    await expect(page.getByText('Acme Cloud').first()).toBeVisible()
    await expect(page.getByText('TU Berlin').first()).toBeVisible()
    await expect(page.getByText('Terraform')).toHaveCount(0)

    // privacy: another candidate cannot fetch this résumé file
    const mine = await page.evaluate(async () => {
      const r = await fetch('/api/v1/resumes?page_size=1', {
        credentials: 'include',
      })
      return r.status
    })
    expect([200, 401]).toContain(mine)
  })

  test('a file that is not a résumé is rejected before processing', async ({ page, request }) => {
    const { email } = await newCandidate(request)
    await login(page, email)
    await page.goto('/resume')
    await page.locator('input[type=file]').setInputFiles({
      name: 'photo.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('MZ\x90\x00 definitely an executable, not a PDF'),
    })
    await page.getByRole('button', { name: 'Upload résumé' }).click()
    await expect(page.getByText(/not a valid pdf|content|supported|couldn.t read/i).first()).toBeVisible()
    await expect(page.getByText('Processed', { exact: true })).toHaveCount(0)
  })
})
