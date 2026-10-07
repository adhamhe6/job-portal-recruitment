// Visual QA: drives the running dev server (npm run dev) with Playwright and saves screenshots to ./screenshots.
//   node scripts/screenshots.mjs                      # everything, all widths
//   node scripts/screenshots.mjs --only=home,jobs     # subset of scenarios (prefix match)
//   node scripts/screenshots.mjs --widths=1440,390
// Env: BASE_URL (default http://127.0.0.1:5173), PLAYWRIGHT_MODULE (path to the playwright package)
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const require = createRequire(import.meta.url)
const candidates = [
  process.env.PLAYWRIGHT_MODULE,
  'playwright',
  '/opt/node-tools/node_modules/playwright',
].filter(Boolean)
let chromium
for (const c of candidates) {
  try {
    ;({ chromium } = require(c))
    break
  } catch {
    /* try next */
  }
}
if (!chromium) throw new Error('playwright not found; set PLAYWRIGHT_MODULE')

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const PASSWORD = 'DemoPass123!'
const arg = (name) => process.argv.find((a) => a.startsWith(`--${name}=`))?.split('=')[1]
const only = arg('only')?.split(',')
const WIDTHS = (arg('widths') ?? '1440,1024,768,390').split(',').map(Number)
const OUT = join(process.cwd(), 'screenshots')
mkdirSync(OUT, { recursive: true })

function chromePath() {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH ?? '/opt/pw-browsers'
  const dir = readdirSync(root).find((d) => d.startsWith('chromium-'))
  const p = join(root, dir, 'chrome-linux', 'chrome')
  return existsSync(p) ? p : undefined
}

const browser = await chromium.launch({ executablePath: chromePath(), args: ['--no-sandbox'] })
const problems = []

async function newSession(label, { dark = false } = {}) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: dark ? 'dark' : 'light',
    reducedMotion: 'reduce',
  })
  const page = await context.newPage()
  page.on('pageerror', (e) => problems.push(`[${label}] pageerror: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text()))
      problems.push(`[${label}] console: ${m.text().slice(0, 300)}`)
  })
  return { context, page }
}

async function login(page, email) {
  await page.goto(`${BASE}/login`)
  await page.getByLabel('Email').fill(email)
  await page.locator('input[autocomplete="current-password"]').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.waitForURL('**/dashboard')
}

async function shot(page, name, { full = true } = {}) {
  for (const w of WIDTHS) {
    await page.setViewportSize({ width: w, height: w < 500 ? 844 : 900 })
    await page.waitForTimeout(350)
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    if (overflow > 1) problems.push(`[${name}@${w}] horizontal page overflow ${overflow}px`)
    await page.screenshot({ path: join(OUT, `${name}-${w}.png`), fullPage: full })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
}

const want = (key) => !only || only.some((o) => key.startsWith(o))
const settle = async (page) => {
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(250)
}

// ---- anonymous -------------------------------------------------------------------------------------------------------------------
if (want('anon') || want('home') || want('login') || want('register') || want('jobs') || want('job-detail')) {
  const { page, context } = await newSession('anon')
  if (want('home')) {
    await page.goto(BASE)
    await settle(page)
    await shot(page, 'home')
  }
  if (want('login')) {
    await page.goto(`${BASE}/login`)
    await settle(page)
    await shot(page, 'login')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.waitForTimeout(300)
    await shot(page, 'login-errors', { full: false })
  }
  if (want('register')) {
    await page.goto(`${BASE}/register`)
    await settle(page)
    await shot(page, 'register')
    await page.goto(`${BASE}/register/employer`)
    await settle(page)
    await shot(page, 'register-employer')
  }
  if (want('jobs')) {
    await page.goto(`${BASE}/jobs`)
    await settle(page)
    await shot(page, 'jobs-anon')
    await page.goto(`${BASE}/jobs?q=zzzzqqq`)
    await settle(page)
    await shot(page, 'jobs-empty', { full: false })
    await page.route('**/api/v1/search/jobs*', (r) =>
      r.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          error: {
            code: 'INTERNAL_ERROR',
            message: 'An unexpected error occurred',
            details: null,
            request_id: 'req-demo-123',
          },
        }),
      }),
    )
    await page.goto(`${BASE}/jobs`)
    await page.waitForTimeout(2500)
    await shot(page, 'jobs-error', { full: false })
    await page.unroute('**/api/v1/search/jobs*')
  }
  if (want('job-detail')) {
    await page.goto(`${BASE}/jobs`)
    await settle(page)
    await page.locator('article h3 a').first().click()
    await settle(page)
    await shot(page, 'job-detail-anon')
  }
  await context.close()
}

// ---- candidate -----------------------------------------------------------------------------------------------------------------------
if (want('cand')) {
  const { page, context } = await newSession('candidate')
  await login(page, 'candidate@demo.example')
  await page.goto(`${BASE}/jobs?skill=Python&skill=PostgreSQL`)
  await settle(page)
  await shot(page, 'cand-jobs-filtered')
  await page.goto(`${BASE}/jobs?sort=match`)
  await settle(page)
  await shot(page, 'cand-jobs-match', { full: false })
  // mobile filter sheet
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: /Filters/ }).click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: join(OUT, 'cand-jobs-filter-sheet-390.png') })
  await page.keyboard.press('Escape')
  await page.setViewportSize({ width: 1440, height: 900 })
  // job detail (not yet applied: DevOps Engineer) + apply dialog
  await page.goto(`${BASE}/jobs?q=DevOps`)
  await settle(page)
  await page.locator('article h3 a').first().click()
  await settle(page)
  await shot(page, 'cand-job-detail')
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.getByRole('button', { name: 'Apply now' }).click()
  await page.waitForTimeout(500)
  await shot(page, 'cand-apply-dialog', { full: false })
  await page.keyboard.press('Escape')
  // applied job
  await page.goto(`${BASE}/jobs?q=Senior+Backend`)
  await settle(page)
  await page.locator('article h3 a').first().click()
  await settle(page)
  await shot(page, 'cand-job-detail-applied', { full: false })
  await page.goto(`${BASE}/jobs/saved`)
  await settle(page)
  await shot(page, 'cand-saved', { full: false })
  await page.goto(`${BASE}/notifications`)
  await settle(page)
  await shot(page, 'cand-notifications')
  await page.goto(`${BASE}/dashboard`)
  await settle(page)
  await page.getByRole('button', { name: /^Notifications/ }).click()
  await page.waitForTimeout(500)
  await shot(page, 'cand-bell', { full: false })
  await page.keyboard.press('Escape')
  await page.goto(`${BASE}/settings`)
  await settle(page)
  await shot(page, 'cand-settings')
  await context.close()
}

// ---- recruiter -----------------------------------------------------------------------------------------------------------------------
if (want('rec')) {
  const { page, context } = await newSession('recruiter')
  await login(page, 'recruiter@demo.example')
  await page.goto(`${BASE}/manage/jobs`)
  await settle(page)
  await shot(page, 'rec-manage-jobs')
  await page.goto(`${BASE}/manage/jobs?status=DRAFT`)
  await settle(page)
  await shot(page, 'rec-manage-drafts', { full: false })
  await page.goto(`${BASE}/manage/jobs?q=Backend`)
  await settle(page)
  await page.locator('a', { hasText: 'Senior Backend Engineer' }).first().click()
  await settle(page)
  await shot(page, 'rec-job-detail')
  await page.goto(`${BASE}/manage/jobs/new`)
  await settle(page)
  await shot(page, 'rec-job-new')
  await page.getByRole('button', { name: 'Publish' }).click()
  await page.waitForTimeout(500)
  await shot(page, 'rec-job-new-errors', { full: false })
  await page.goto(`${BASE}/manage/jobs?status=PUBLISHED`)
  await settle(page)
  await page
    .getByRole('button', { name: /^Actions for/ })
    .first()
    .click()
  await page.waitForTimeout(300)
  await shot(page, 'rec-row-menu', { full: false })
  await context.close()
}

// ---- dark mode -------------------------------------------------------------------------------------------------------------------------
if (want('dark')) {
  const { page, context } = await newSession('dark', { dark: true })
  await page.goto(BASE)
  await settle(page)
  await shot(page, 'dark-home', { full: false })
  await page.goto(`${BASE}/jobs`)
  await settle(page)
  await shot(page, 'dark-jobs', { full: false })
  await login(page, 'candidate@demo.example')
  await page.goto(`${BASE}/jobs?q=Backend`)
  await settle(page)
  await page.locator('article h3 a').first().click()
  await settle(page)
  await shot(page, 'dark-job-detail', { full: false })
  await context.close()
  const rec = await newSession('dark-rec', { dark: true })
  await login(rec.page, 'recruiter@demo.example')
  await rec.page.goto(`${BASE}/manage/jobs/new`)
  await settle(rec.page)
  await shot(rec.page, 'dark-job-new', { full: false })
  await rec.page.goto(`${BASE}/manage/jobs`)
  await settle(rec.page)
  await shot(rec.page, 'dark-manage', { full: false })
  await rec.context.close()
}

await browser.close()
console.log(
  problems.length
    ? `PROBLEMS (${problems.length}):\n${[...new Set(problems)].join('\n')}`
    : 'No console errors or page overflow detected.',
)
console.log(`Screenshots in ${OUT}`)
