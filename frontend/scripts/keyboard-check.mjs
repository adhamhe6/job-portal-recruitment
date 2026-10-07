// Keyboard & focus audit against the running dev server: skip link, menus, dialogs, sheets, comboboxes.
import { createRequire } from 'node:module'
import { readdirSync } from 'node:fs'
import { join } from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? '/opt/node-tools/node_modules/playwright')
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const root = process.env.PLAYWRIGHT_BROWSERS_PATH ?? '/opt/pw-browsers'
const chrome = join(
  root,
  readdirSync(root).find((d) => d.startsWith('chromium-')),
  'chrome-linux',
  'chrome',
)
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
const assert = (c, m) => {
  if (!c) throw new Error(m)
}
const focusedName = (page) =>
  page.evaluate(() => {
    const el = document.activeElement
    return el ? (el.getAttribute('aria-label') ?? el.textContent ?? el.tagName).trim().slice(0, 60) : null
  })
const insideDialog = (page) =>
  page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"],[role="alertdialog"]')))

async function login(page, email) {
  await page.goto(`${BASE}/login`)
  await page.getByLabel('Email').fill(email)
  await page.locator('input[autocomplete="current-password"]').fill('DemoPass123!')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.waitForURL('**/dashboard')
}

const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()
await login(page, 'candidate@demo.example')

console.log('Candidate shell')
await step('skip link is the first tab stop and moves focus to <main>', async () => {
  await page.goto(`${BASE}/jobs`)
  await page.waitForSelector('article')
  await page.keyboard.press('Tab')
  assert(
    (await focusedName(page)) === 'Skip to main content',
    `first tab stop was "${await focusedName(page)}"`,
  )
  await page.keyboard.press('Enter')
  assert(await page.evaluate(() => location.hash === '#main-content'), 'hash should be #main-content')
})
await step('user menu: Enter opens, arrows move, Escape closes and returns focus', async () => {
  const trigger = page.getByRole('button', { name: /Account menu for/ })
  await trigger.focus()
  await page.keyboard.press('Enter')
  await page.getByRole('menu').waitFor()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('ArrowDown')
  assert((await focusedName(page)).length > 0, 'menu item should have focus')
  await page.keyboard.press('Escape')
  await page.getByRole('menu').waitFor({ state: 'detached' })
  assert(
    await trigger.evaluate((el) => el === document.activeElement),
    'focus should return to the user-menu button',
  )
})
await step('theme menu is keyboard operable and persists', async () => {
  await page.getByRole('button', { name: /^Theme:/ }).focus()
  await page.keyboard.press('Enter')
  await page.getByRole('menuitem', { name: 'Dark' }).click()
  assert(
    await page.evaluate(() => document.documentElement.classList.contains('dark')),
    'dark class expected',
  )
  await page.reload()
  assert(
    await page.evaluate(() => document.documentElement.classList.contains('dark')),
    'theme should persist across reload (no flash)',
  )
  await page.getByRole('button', { name: /^Theme:/ }).click()
  await page.getByRole('menuitem', { name: 'System' }).click()
})
await step('"/" focuses the global search; Enter submits to the job search', async () => {
  await page.goto(`${BASE}/dashboard`)
  await page.keyboard.press('/')
  assert((await focusedName(page)) === 'Search jobs', 'search input should be focused')
  await page.keyboard.type('devops')
  await page.keyboard.press('Enter')
  await page.waitForURL('**/jobs?q=devops')
})
await step('filters: skill combobox works by keyboard (type, ArrowDown, Enter)', async () => {
  await page.goto(`${BASE}/jobs`)
  const picker = page.getByRole('combobox', { name: 'Skills' })
  await picker.focus()
  await page.keyboard.press('Enter')
  await page.getByPlaceholder('Type a skill name…').fill('kube')
  await page.getByRole('option', { name: /Kubernetes/ }).waitFor()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await page.waitForURL('**skill=Kubernetes**')
})
await step(
  'apply dialog traps focus (Tab and Shift+Tab never leave it) and Escape restores focus',
  async () => {
    await page.goto(`${BASE}/jobs?q=DevOps`)
    await page.locator('article h3 a').first().click()
    const apply = page.getByRole('button', { name: 'Apply now' })
    await apply.focus()
    await page.keyboard.press('Enter')
    await page.getByRole('dialog').waitFor()
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Tab')
      assert(await insideDialog(page), `focus escaped the dialog on Tab #${i + 1}`)
    }
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Shift+Tab')
      assert(await insideDialog(page), `focus escaped the dialog on Shift+Tab #${i + 1}`)
    }
    await page.keyboard.press('Escape')
    await page.getByRole('dialog').waitFor({ state: 'detached' })
    assert(await apply.evaluate((el) => el === document.activeElement), 'focus should return to Apply now')
  },
)
await step('mobile navigation sheet traps focus and closes with Escape', async () => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`${BASE}/dashboard`)
  const menu = page.getByRole('button', { name: 'Open navigation menu' })
  await menu.focus()
  await page.keyboard.press('Enter')
  await page.getByRole('dialog').waitFor()
  for (let i = 0; i < 14; i++) {
    await page.keyboard.press('Tab')
    assert(await insideDialog(page), `focus escaped the sheet on Tab #${i + 1}`)
  }
  await page.keyboard.press('Escape')
  await page.getByRole('dialog').waitFor({ state: 'detached' })
  assert(await menu.evaluate((el) => el === document.activeElement), 'focus should return to the menu button')
})
await ctx.close()

console.log('Recruiter')
await new Promise((r) => setTimeout(r, 1000))
const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const rec = await ctx2.newPage()
await login(rec, 'recruiter@demo.example')
await step('row action menu + confirmation dialog are keyboard operable', async () => {
  await rec.goto(`${BASE}/manage/jobs?status=PUBLISHED`)
  const trigger = rec.getByRole('button', { name: /^Actions for/ }).first()
  await trigger.focus()
  await rec.keyboard.press('Enter')
  await rec.getByRole('menu').waitFor()
  await rec.getByRole('menuitem', { name: 'Close' }).focus()
  await rec.keyboard.press('Enter')
  await rec.getByRole('alertdialog').waitFor()
  assert(await insideDialog(rec), 'focus should be inside the confirmation')
  await rec.keyboard.press('Escape')
  await rec.getByRole('alertdialog').waitFor({ state: 'detached' })
  assert(
    await trigger.evaluate((el) => el === document.activeElement),
    'focus should return to the row action button',
  )
})
await step('job form: first invalid field receives focus on a failed submit', async () => {
  await rec.goto(`${BASE}/manage/jobs/new`)
  await rec.getByRole('button', { name: /save as draft/i }).click()
  await rec.waitForFunction(() => document.activeElement?.getAttribute('aria-invalid') === 'true')
})
await ctx2.close()
await browser.close()
console.log(failures ? `\n${failures} step(s) FAILED` : '\nAll keyboard checks passed.')
process.exit(failures ? 1 : 0)
