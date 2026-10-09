import { expect, type Page, type APIRequestContext } from '@playwright/test'

export const PASSWORD = 'DemoPass123!'
export const ACCOUNTS = {
  candidate: 'candidate@demo.example',
  recruiter: 'recruiter@demo.example',
  admin: 'admin@demo.example',
} as const

export async function login(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Email' }).fill(email)
  await page.getByRole('textbox', { name: 'Password' }).fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).not.toHaveURL(/\/login/)
}

/** API login for setup/verification that is not the point of the scenario under test. */
export async function apiToken(request: APIRequestContext, email: string): Promise<string> {
  const res = await request.post('/api/v1/auth/login', {
    data: { email, password: PASSWORD },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  return (await res.json()).access_token as string
}

export const bearer = (token: string) => ({ Authorization: `Bearer ${token}` })

export function uniqueSuffix(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}

/** A brand-new candidate account (API-created so the scenario under test starts from a clean slate). */
export async function newCandidate(request: APIRequestContext): Promise<{ email: string; first: string }> {
  const email = `e2e.${uniqueSuffix()}@example.com`
  const first = 'Eve'
  const res = await request.post('/api/v1/auth/register', {
    data: {
      email,
      password: PASSWORD,
      first_name: first,
      last_name: 'Tester',
      role: 'CANDIDATE',
    },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  return { email, first }
}

import { PDFDocument, StandardFonts } from 'pdf-lib'

/** A small but realistic text-based résumé PDF (what the parser is built for). */
export async function resumePdf(name: string): Promise<Buffer> {
  const doc = await PDFDocument.create()
  const font = await doc.embedFont(StandardFonts.Helvetica)
  const bold = await doc.embedFont(StandardFonts.HelveticaBold)
  const page = doc.addPage([595, 842])
  let y = 790
  const line = (text: string, opts: { bold?: boolean; size?: number } = {}) => {
    page.drawText(text, {
      x: 50,
      y,
      size: opts.size ?? 11,
      font: opts.bold ? bold : font,
    })
    y -= (opts.size ?? 11) + 7
  }
  line(name, { bold: true, size: 20 })
  line('Backend Engineer - Python, PostgreSQL and Docker')
  line('eve.tester@example.com | Berlin, Germany')
  y -= 8
  line('Summary', { bold: true, size: 13 })
  line('Backend engineer with four years of experience building APIs with Python, FastAPI and PostgreSQL.')
  y -= 8
  line('Skills', { bold: true, size: 13 })
  line('Python, FastAPI, PostgreSQL, Redis, Docker, Kubernetes, Terraform, Git, CI/CD')
  y -= 8
  line('Experience', { bold: true, size: 13 })
  line('Backend Engineer - Acme Cloud (2022 - Present)', { bold: true })
  line('Built REST APIs with FastAPI and PostgreSQL; deployed with Docker and Kubernetes on AWS.')
  line('Software Engineer - Shipwise (2020 - 2022)', { bold: true })
  line('Developed Python services and automated CI/CD pipelines with GitHub Actions.')
  y -= 8
  line('Education', { bold: true, size: 13 })
  line('BSc Computer Science, TU Berlin (2016 - 2020)')
  return Buffer.from(await doc.save())
}
