import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { makeDashboard, makeMatching, makeSystem } from './fixtures'

const API = '/api/v1'

function mockAll(dashboard = makeDashboard()) {
  server.use(
    http.get(`${API}/reports/admin-dashboard`, () => HttpResponse.json(dashboard)),
    http.get(`${API}/reports/recruiter-dashboard`, () =>
      HttpResponse.json({
        scope: 'platform',
        period: { from_date: '2026-09-10', to_date: '2026-10-09', granularity: 'week' },
        kpis: { total_applications: 19, hires_in_period: 1 },
        applications_over_time: [
          { bucket: '2026-09-28', count: 8 },
          { bucket: '2026-10-05', count: 4 },
        ],
      }),
    ),
    http.get(`${API}/admin/system`, () => HttpResponse.json(makeSystem())),
    http.get(`${API}/admin/matching/status`, () => HttpResponse.json(makeMatching({ stale_by_version: 3 }))),
  )
}

describe('admin dashboard', () => {
  it('shows platform KPIs, chart text alternatives, health and recent audit events', async () => {
    signInAs('ADMIN')
    mockAll()
    renderApp('/dashboard')
    expect(await screen.findByRole('heading', { name: 'Platform overview', level: 1 })).toBeInTheDocument()
    const kpis = await screen.findByRole('region', { name: 'Key figures' })
    expect(await within(kpis).findByText('25')).toBeInTheDocument()
    expect(within(kpis).getByText('1 suspended')).toBeInTheDocument()
    expect(within(kpis).getByText('3 active · 1 suspended')).toBeInTheDocument()
    expect(within(kpis).getByText('10')).toBeInTheDocument() // published jobs
    expect(within(kpis).getByText('205')).toBeInTheDocument() // match pairs

    // Charts carry a text alternative and a data table.
    const roleChart = await screen.findByRole('img', {
      name: /Users by role\. Administrator: 2, Recruiter: 5/,
    })
    expect(roleChart).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Applications by status' })).toBeInTheDocument()
    expect(
      await screen.findByRole('img', { name: /Applications received.*12 applications/ }),
    ).toBeInTheDocument()

    // Health + audit
    expect(await screen.findByText('Operational')).toBeInTheDocument()
    expect(screen.getByText(/Matching: 205 pairs, 3 outdated/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open system monitoring/i })).toHaveAttribute(
      'href',
      '/admin/system',
    )
    expect(screen.getByText('Job archived')).toBeInTheDocument()
  })

  it('degrades per section: failed report keeps the rest, retry recovers', async () => {
    signInAs('ADMIN')
    mockAll()
    let failing = true
    server.use(
      http.get(`${API}/reports/admin-dashboard`, () =>
        failing
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 })
          : HttpResponse.json(makeDashboard()),
      ),
    )
    const { user } = renderApp('/dashboard')
    // Health summary still renders while dashboard sections show errors.
    expect(await screen.findByText('Operational')).toBeInTheDocument()
    const retries = await screen.findAllByRole('button', { name: /try again/i })
    expect(retries.length).toBeGreaterThan(0)
    failing = false
    await user.click(retries[0]!)
    expect(await screen.findByText('Job archived')).toBeInTheDocument()
  })

  it('shows empty sections for a brand-new platform', async () => {
    signInAs('ADMIN')
    mockAll(
      makeDashboard({
        users_total: 0,
        recent_audit_events: [],
        signups_over_time: [],
        applications_by_status: {},
        jobs_by_status: {},
        users_by_role: {},
      }),
    )
    renderApp('/dashboard')
    expect(await screen.findByText('No activity recorded yet')).toBeInTheDocument()
    expect(screen.getAllByText(/no data yet/).length).toBeGreaterThan(0)
  })
})
