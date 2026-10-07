// End-to-end smoke test against the REAL stack (Vite dev server -> /api proxy -> FastAPI). Not part of `npm test`.
//   npm run dev &   then   node scripts/e2e-smoke.mjs
// It only leaves net-zero data behind: a scratch draft job is created and deleted; saved-job toggles are reverted.
import { createRequire } from 'node:module'
import { readdirSync } from 'node:fs'
import { join } from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? '/opt/node-tools/node_modules/playwright')
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const PASSWORD = 'DemoPass123!'
const root = process.env.PLAYWRIGHT_BROWSERS_PATH ?? '/opt/pw-browsers'
const chrome = join(root, readdirSync(root).find((d) => d.startsWith('chromium-')), 'chrome-linux', 'chrome')

const browser = await chromium.launch({ executablePath: chrome, args: ['--no-sandbox'] })
let failures = 0
const step = async (name, fn) => {
  try {
    await fn()
    console.log(`  ok   ${name}`)
  } catch (e) {
    failures++
    console.log(`  FAIL ${name}\n       ${String(e.message).split('\n')[0]}`)
  }
}
const assert = (cond, msg) => {
  if (!cond) throw new Error(msg)
}
async function session(email) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  if (email) {
    await page.goto(`${BASE}/login`)
    await page.getByLabel('Email').fill(email)
    await page.locator('input[autocomplete="current-password"]').fill(PASSWORD)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.waitForURL('**/dashboard')
  }
  return { page, context, errors }
}
const api = async (path) => (await fetch(`http://localhost:8000/api/v1${path}`)).json()

console.log('Anonymous visitor')
{
  const { page, context, errors } = await session()
  await step('landing page shows live featured jobs', async () => {
    await page.goto(BASE)
    await page.waitForSelector('article h3')
    assert((await page.locator('article').count()) === 6, 'expected 6 featured jobs')
  })
  await step('job search count matches the API', async () => {
    const expected = (await api('/search/jobs?page_size=1')).total
    await page.goto(`${BASE}/jobs`)
    await page.getByText(`${expected} jobs found`).waitFor()
  })
  await step('workplace filter updates the URL and the result count (shareable link)', async () => {
    const expected = (await api('/search/jobs?workplace_type=REMOTE&page_size=1')).total
    await page.goto(`${BASE}/jobs`)
    await page.getByRole('checkbox', { name: 'Remote' }).click()
    await page.waitForURL('**workplace_type=REMOTE**')
    await page.getByText(new RegExp(`^${expected} jobs? found`)).waitFor()
    // the same link in a fresh page restores the same filtered view
    await page.goto(page.url())
    await page.getByText(new RegExp(`^${expected} jobs? found`)).waitFor()
    assert(await page.getByRole('checkbox', { name: 'Remote' }).isChecked(), 'checkbox should reflect the URL')
  })
  await step('keyword search + skill autocomplete', async () => {
    await page.goto(`${BASE}/jobs`)
    await page.getByRole('combobox', { name: 'Skills' }).click()
    await page.getByPlaceholder('Type a skill name…').fill('postg')
    await page.getByRole('option', { name: /PostgreSQL/ }).click()
    await page.waitForURL('**skill=PostgreSQL**')
    const expected = (await api('/search/jobs?skill=PostgreSQL&page_size=1')).total
    await page.getByText(new RegExp(`^${expected} jobs? found`)).waitFor()
  })
  await step('job detail for a visitor offers sign-in, not apply', async () => {
    await page.goto(`${BASE}/jobs`)
    await page.locator('article h3 a').first().click()
    await page.getByRole('link', { name: 'Sign in to apply' }).waitFor()
  })
  await step('unknown job id shows a friendly error', async () => {
    await page.goto(`${BASE}/jobs/00000000-0000-0000-0000-000000000000`)
    await page.getByText('This job isn’t available').waitFor()
  })
  await step('protected page redirects to login with next=', async () => {
    await page.goto(`${BASE}/applications`)
    await page.waitForURL('**/login?next=%2Fapplications')
  })
  assert(errors.length === 0, `page errors: ${errors.join('; ')}`)
  await context.close()
}

console.log('Candidate (Alex Rivera)')
{
  const { page, context, errors } = await session('candidate@demo.example')
  await step('search shows match percentages and applied badge', async () => {
    await page.goto(`${BASE}/jobs?sort=match`)
    await page.waitForSelector('article')
    assert((await page.locator('article >> text=/\\d+%/').count()) > 0, 'expected match % badges')
    await page.getByText('Applied', { exact: true }).first().waitFor()
  })
  await step('job detail shows the real "How you match" explanation', async () => {
    await page.goto(`${BASE}/jobs?q=DevOps`)
    await page.locator('article h3 a').first().click()
    await page.getByRole('heading', { name: 'How you match' }).waitFor()
    await page.getByRole('button', { name: 'Apply now' }).waitFor()
  })
  await step('save and unsave a job (persisted by the API)', async () => {
    await page.getByRole('button', { name: /^Save DevOps/ }).first().click()
    await page.getByRole('button', { name: /^Remove DevOps.* from saved jobs/ }).first().waitFor()
    await page.reload()
    await page.getByRole('button', { name: /^Remove DevOps.* from saved jobs/ }).first().waitFor()
    await page.goto(`${BASE}/jobs/saved`)
    await page.getByRole('heading', { name: /DevOps Engineer/ }).waitFor()
    await page.getByRole('button', { name: /^Remove DevOps.* from saved jobs/ }).click()
    await page.getByRole('heading', { name: 'No saved jobs yet' }).waitFor()
  })
  await step('apply dialog opens, handles the missing résumés endpoint, and Escape returns focus', async () => {
    await page.goto(`${BASE}/jobs?q=DevOps`)
    await page.locator('article h3 a').first().click()
    const apply = page.getByRole('button', { name: 'Apply now' })
    await apply.click()
    await page.getByRole('dialog').getByText('Upload a résumé first').waitFor()
    await page.keyboard.press('Escape')
    await page.getByRole('dialog').waitFor({ state: 'detached' })
    assert(await apply.evaluate((el) => el === document.activeElement), 'focus should return to the Apply button')
  })
  await step('already-applied job shows status instead of Apply', async () => {
    await page.goto(`${BASE}/jobs?q=Senior+Backend`)
    await page.locator('article h3 a').first().click()
    await page.getByText(/You applied · /).waitFor()
  })
  await step('notifications bell + page', async () => {
    await page.goto(`${BASE}/dashboard`)
    await page.getByRole('button', { name: /^Notifications/ }).click()
    await page.getByRole('dialog').getByText('Application update').first().waitFor()
    await page.keyboard.press('Escape')
    await page.goto(`${BASE}/notifications`)
    await page.getByRole('heading', { name: 'Notifications' }).waitFor()
  })
  await step('staff pages are forbidden for candidates', async () => {
    await page.goto(`${BASE}/manage/jobs`)
    await page.getByText("You don't have access to this page").waitFor()
  })
  await step('session survives a reload (silent refresh through the cookie)', async () => {
    await page.goto(`${BASE}/dashboard`)
    await page.reload()
    await page.getByRole('button', { name: /Account menu for Alex/ }).waitFor()
  })
  await step('sign out returns to /login', async () => {
    await page.getByRole('button', { name: /Account menu for Alex/ }).click()
    await page.getByRole('menuitem', { name: /sign out/i }).click()
    await page.waitForURL('**/login')
    await page.goto(`${BASE}/dashboard`)
    await page.waitForURL('**/login?next=**')
  })
  assert(errors.length === 0, `page errors: ${errors.join('; ')}`)
  await context.close()
}

console.log('Recruiter (Northwind Labs)')
{
  const { page, context, errors } = await session('recruiter@demo.example')
  const title = `QA scratch job ${Date.now()}`
  await step('jobs list shows the company jobs in all statuses', async () => {
    await page.goto(`${BASE}/manage/jobs`)
    await page.getByRole('link', { name: 'Senior Backend Engineer', exact: true }).waitFor()
    await page.getByText('Draft', { exact: true }).first().waitFor()
  })
  await step('client-side publish gate (no round-trip)', async () => {
    await page.goto(`${BASE}/manage/jobs/new`)
    await page.getByLabel(/job title/i).fill(title)
    await page.getByLabel(/about the role/i).fill('Too short.')
    await page.getByRole('button', { name: 'Publish' }).click()
    await page.getByText('Add at least one required skill to publish').first().waitFor()
  })
  await step('create a draft with an existing skill -> lands on its edit page', async () => {
    await page.getByLabel(/about the role/i).fill('A scratch job used by the automated QA run; it is deleted again right away.')
    await page.getByRole('combobox', { name: 'Skills' }).click()
    await page.getByPlaceholder('Type a skill name…').fill('Python')
    await page.getByRole('option', { name: /^Python/ }).first().click()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: /save as draft/i }).click()
    await page.waitForURL('**/manage/jobs/*/edit')
    await page.getByRole('heading', { name: new RegExp(title) }).waitFor()
  })
  await step('server rejects bad data and the error lands on the field (INVALID_DEADLINE/range)', async () => {
    await page.getByLabel(/salary from/i).fill('90000')
    await page.getByLabel(/salary up to/i).fill('50000')
    await page.getByRole('button', { name: /save as draft/i }).click()
    await page.getByText('Maximum salary must be at least the minimum').waitFor()
    await page.getByLabel(/salary up to/i).fill('120000')
  })
  await step('edit + save the draft (PATCH)', async () => {
    await page.getByLabel(/department/i).fill('QA')
    await page.getByRole('button', { name: /save as draft/i }).click()
    await page.getByText('Draft saved').first().waitFor()
  })
  await step('job detail (staff view) + overview for the new draft', async () => {
    await page.getByRole('link', { name: 'View job' }).click()
    await page.getByText('Staff view').waitFor()
    await page.getByText(/not visible to candidates/i).waitFor()
    await page.getByRole('heading', { name: 'Applications by status' }).waitFor()
  })
  await step('delete the draft with confirmation (cleanup)', async () => {
    await page.getByRole('button', { name: /delete draft/i }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Delete draft' }).click()
    await page.waitForURL('**/manage/jobs')
    await page.getByRole('link', { name: 'Senior Backend Engineer', exact: true }).waitFor()
    assert((await page.getByRole('link', { name: title }).count()) === 0, 'scratch job should be gone')
  })
  await step('status tab filters through the API', async () => {
    await page.getByRole('tab', { name: 'Paused' }).click()
    await page.getByRole('link', { name: 'Platform Engineer', exact: true }).waitFor()
    assert((await page.getByRole('link', { name: 'Senior Backend Engineer', exact: true }).count()) === 0, 'published job should be filtered out')
  })
  assert(errors.length === 0, `page errors: ${errors.join('; ')}`)
  await context.close()
}

console.log('Hiring manager & admin')
{
  const hm = await session('hiring.manager@demo.example')
  await step('hiring manager lists only assigned jobs and cannot create', async () => {
    await hm.page.goto(`${BASE}/manage/jobs`)
    await hm.page.getByRole('heading', { name: 'Jobs' }).waitFor()
    assert((await hm.page.getByRole('link', { name: /new job/i }).count()) === 0, 'HM should not see New job')
  })
  await hm.context.close()
  const admin = await session('admin@demo.example')
  await step('admin sees jobs across companies', async () => {
    await admin.page.goto(`${BASE}/manage/jobs`)
    await admin.page.getByText('All jobs across companies.').waitFor()
    await admin.page.getByRole('link', { name: /Financial Analyst|Clinical Data Analyst|Marketing Manager/ }).first().waitFor()
  })
  await admin.context.close()
}

await browser.close()
console.log(failures ? `\n${failures} step(s) FAILED` : '\nAll smoke steps passed.')
process.exit(failures ? 1 : 0)
