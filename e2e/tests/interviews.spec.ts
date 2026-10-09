import { expect, test } from '@playwright/test'
import { ACCOUNTS, apiToken, bearer, login } from './helpers'

test.describe('workflow 5 · interviews: scheduling conflicts, candidate confirmation, feedback', () => {
  test('a double-booked interviewer is refused with a clear conflict message; the candidate confirms attendance', async ({
    browser,
    page,
    request,
  }) => {
    // Alex Rivera's seeded phone screen (Riley Recruiter + Hannah Manager) is the slot we try to collide with.
    const token = await apiToken(request, ACCOUNTS.recruiter)
    const list = await request.get('/api/v1/interviews?upcoming_only=true&page_size=50', { headers: bearer(token) })
    expect(list.ok()).toBeTruthy()
    const existing = (await list.json()).items.find(
      (i: { candidate_name?: string; candidate?: { display_name?: string } }) =>
        JSON.stringify(i).includes('Alex Rivera'),
    )
    expect(existing, 'the seed provides an upcoming interview for Alex Rivera').toBeTruthy()
    const start = new Date(existing.start_at)
    const clash = new Date(start.getTime() + 30 * 60_000) // 30 minutes into the existing slot
    const local = (d: Date) => d.toISOString().slice(0, 16)

    // --- recruiter tries to book Nina Petrova into the same slot with the same interviewer
    await login(page, ACCOUNTS.recruiter)
    await page.goto('/interviews')
    await expect(page.getByRole('link', { name: /Alex Rivera/ })).toBeVisible()
    await page.getByRole('button', { name: 'Schedule interview' }).first().click()
    await page.getByRole('combobox', { name: 'Application' }).click()
    await page.getByRole('option', { name: /Nina Petrova/ }).click()
    const form = page.getByRole('dialog', { name: 'Schedule interview' })
    await form.getByLabel('Starts').fill(local(clash))
    await form.getByLabel('Ends').fill(local(new Date(clash.getTime() + 45 * 60_000)))
    await form.getByLabel('Meeting link').fill('https://meet.example.com/e2e-conflict')
    await form.getByRole('button', { name: 'Schedule interview' }).click()
    // refused: the dialog stays open and names who is already booked
    await expect(form.getByText(/already|booked|conflict/i).first()).toBeVisible()
    await expect(form).toBeVisible()

    // --- a free slot is accepted
    const free = new Date(start.getTime() + 3 * 24 * 3600_000)
    await form.getByLabel('Starts').fill(local(free))
    await form.getByLabel('Ends').fill(local(new Date(free.getTime() + 45 * 60_000)))
    await form.getByRole('button', { name: 'Schedule interview' }).click()
    await expect(page.getByRole('link', { name: /Nina Petrova/ })).toBeVisible()

    // --- the candidate sees their interview and confirms attendance
    const cand = await (await browser.newContext({ baseURL: 'http://localhost:8080' })).newPage()
    await login(cand, ACCOUNTS.candidate)
    await cand.goto('/interviews')
    await expect(cand.getByText(/phone screen/i).first()).toBeVisible()
    const confirm = cand.getByRole('button', { name: /confirm attendance/i }).first()
    if (await confirm.isVisible()) await confirm.click()
    await expect(cand.getByText(/confirmed/i).first()).toBeVisible()
    await cand.context().close()
  })

  test('feedback is internal: staff can read it, the candidate never receives it', async ({ page, request }) => {
    const token = await apiToken(request, ACCOUNTS.recruiter)
    const done = await request.get('/api/v1/interviews?status=COMPLETED&page_size=5', { headers: bearer(token) })
    const completed = (await done.json()).items[0]
    expect(completed, 'the seed provides completed interviews with feedback').toBeTruthy()

    // staff view shows the feedback
    await login(page, ACCOUNTS.recruiter)
    await page.goto(`/interviews/${completed.id}`)
    await expect(page.getByText(/feedback/i).first()).toBeVisible()
    await expect(page.getByText(/recommendation|strengths/i).first()).toBeVisible()

    // the API refuses the candidate role outright
    const candToken = await apiToken(request, ACCOUNTS.candidate)
    const res = await request.get(`/api/v1/interviews/${completed.id}/feedback`, { headers: bearer(candToken) })
    expect([403, 404]).toContain(res.status())
  })
})
