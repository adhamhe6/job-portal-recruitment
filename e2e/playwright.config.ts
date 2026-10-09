import { defineConfig, devices } from '@playwright/test'
import { existsSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

// Use the preinstalled Chromium when PLAYWRIGHT_BROWSERS_PATH is set (sandboxes); CI installs its own.
function localChromium(): string | undefined {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH
  if (!root || !existsSync(root)) return undefined
  const dir = readdirSync(root).find((d) => /^chromium-\d+$/.test(d))
  if (!dir) return undefined
  const candidates = [
    join(root, dir, 'chrome-linux', 'chrome'),
    join(root, dir, 'chrome-linux64', 'chrome'),
    join(root, dir, 'chrome'),
  ]
  return candidates.find(existsSync)
}

export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false, // the scenarios share one seeded database and a single worker queue
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    launchOptions: { executablePath: process.env.E2E_CHROMIUM_PATH ?? localChromium() },
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
})
