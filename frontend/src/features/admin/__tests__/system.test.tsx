import { act, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { errorBody, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import { makeAudit, makeEmbeddings, makeMatching, makeSystem, makeTask } from './fixtures'

const API = '/api/v1'

function mockSystem(system = makeSystem()) {
  server.use(http.get(`${API}/admin/system`, () => HttpResponse.json(system)))
}

describe('system monitoring: health', () => {
  it('shows dependency health, worker and model status', async () => {
    signInAs('ADMIN')
    mockSystem()
    renderApp('/admin/system')
    expect(await screen.findByRole('heading', { name: 'System monitoring', level: 1 })).toBeInTheDocument()
    expect(await screen.findByText('All systems operational')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Database' })).toBeInTheDocument()
    expect(screen.getByText('Alive')).toBeInTheDocument()
    expect(screen.getByText('Loaded')).toBeInTheDocument()
    expect(screen.getByText('wordllama-l2')).toBeInTheDocument()
  })

  it('flags a degraded system: dead worker, behind migrations, redis error with a capped message', async () => {
    signInAs('ADMIN')
    mockSystem(
      makeSystem({
        status: 'degraded',
        redis: { ok: false, latency_ms: null, queue_depth: null, error: 'x'.repeat(400) },
        worker: { ...makeSystem().worker, alive: false },
        database: {
          ...makeSystem().database,
          migrations_current: false,
          migration_revision: '0001',
          migration_head: '0002',
        },
      }),
    )
    renderApp('/admin/system')
    expect(await screen.findByText(/Degraded: something needs attention/)).toBeInTheDocument()
    expect(screen.getByText('Not responding')).toBeInTheDocument()
    expect(screen.getByText('Migrations behind')).toBeInTheDocument()
    expect(screen.getByText('Unreachable')).toBeInTheDocument()
    const alerts = screen.getAllByRole('alert')
    expect(
      alerts.some((a) => (a.textContent ?? '').length <= 201 && (a.textContent ?? '').endsWith('…')),
    ).toBe(true)
  })

  it('shows an error with retry when the status endpoint fails', async () => {
    signInAs('ADMIN')
    let failing = true
    server.use(
      http.get(`${API}/admin/system`, () =>
        failing
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 })
          : HttpResponse.json(makeSystem()),
      ),
    )
    const { user } = renderApp('/admin/system')
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    failing = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByText('All systems operational')).toBeInTheDocument()
  })

  it('polls while auto-refresh is on and stops when it is switched off', async () => {
    signInAs('ADMIN')
    let calls = 0
    server.use(
      http.get(`${API}/admin/system`, () => {
        calls += 1
        return HttpResponse.json(makeSystem())
      }),
    )
    // Only intervals are faked (set up before rendering so TanStack Query's poll timer is the fake one).
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      const { user } = renderApp('/admin/system')
      await screen.findByText('All systems operational')
      const toggle = screen.getByRole('switch', { name: 'Auto-refresh' })
      expect(toggle).toBeChecked()
      const before = calls
      await act(async () => {
        await vi.advanceTimersByTimeAsync(16_000)
      })
      await waitFor(() => expect(calls).toBeGreaterThan(before))
      await user.click(toggle)
      expect(toggle).not.toBeChecked()
      expect(localStorage.getItem('talentlens.admin.autorefresh')).toBe('off')
      await new Promise((r) => setTimeout(r, 50))
      const afterOff = calls
      await act(async () => {
        await vi.advanceTimersByTimeAsync(40_000)
      })
      await new Promise((r) => setTimeout(r, 50))
      expect(calls).toBe(afterOff)
    } finally {
      vi.useRealTimers()
    }
  })

  it('refreshes immediately with "Refresh now"', async () => {
    signInAs('ADMIN')
    let calls = 0
    server.use(
      http.get(`${API}/admin/system`, () => {
        calls += 1
        return HttpResponse.json(makeSystem())
      }),
    )
    const { user } = renderApp('/admin/system')
    await screen.findByText('All systems operational')
    const before = calls
    await user.click(screen.getByRole('button', { name: /refresh now/i }))
    await waitFor(() => expect(calls).toBeGreaterThan(before))
  })
})

describe('system monitoring: background tasks', () => {
  const failed = makeTask({
    id: 'deadbeef-0000-0000-0000-000000000009',
    type: 'PROCESS_RESUME',
    status: 'FAILED',
    progress: 40,
    error_code: 'RESUME_PARSE_FAILED',
    error_message: 'Could not read the file.\n   ' + 'detail '.repeat(100),
  })

  it('lists tasks with filters, failures with a safe message, and stuck tasks', async () => {
    signInAs('ADMIN')
    mockSystem(
      makeSystem({
        tasks: {
          ...makeSystem().tasks,
          by_status: { PENDING: 1, RUNNING: 1, COMPLETED: 10, FAILED: 1 },
          stale_count: 2,
          stale: [
            {
              id: 'aaaaaaaa-0000-0000-0000-000000000001',
              type: 'MATCH_JOB',
              status: 'RUNNING',
              stage: 'scoring',
              created_at: '2026-10-09T08:00:00Z',
              updated_at: '2026-10-09T08:05:00Z',
              age_minutes: 52.4,
              worker_heartbeat: false,
            },
          ],
        },
      }),
    )
    const seen: URLSearchParams[] = []
    server.use(
      http.get(`${API}/admin/tasks`, ({ request }) => {
        seen.push(new URL(request.url).searchParams)
        return HttpResponse.json(page([failed, makeTask()]))
      }),
    )
    const { user } = renderApp('/admin/system?tab=tasks')
    const table = await screen.findByRole('table', { name: /background tasks/i })
    expect(within(table).getByText('RESUME_PARSE_FAILED')).toBeInTheDocument()
    const msg = within(table).getByText(/Could not read the file\./)
    expect((msg.textContent ?? '').length).toBeLessThanOrEqual(200)
    expect(await screen.findByText('2 tasks look stuck')).toBeInTheDocument()
    expect(screen.getByText(/worker heartbeat missing/)).toBeInTheDocument()

    await user.click(screen.getByRole('combobox', { name: 'Filter tasks by status' }))
    await user.click(await screen.findByRole('option', { name: 'Failed' }))
    await waitFor(() => expect(seen.at(-1)?.get('status')).toBe('FAILED'))
    await user.click(screen.getByRole('combobox', { name: 'Filter tasks by type' }))
    await user.click(await screen.findByRole('option', { name: 'Résumé processing' }))
    await waitFor(() => expect(seen.at(-1)?.get('type')).toBe('PROCESS_RESUME'))
  })

  it('retries a failed task and explains a 409', async () => {
    signInAs('ADMIN')
    mockSystem()
    let attempts = 0
    server.use(
      http.get(`${API}/admin/tasks`, () => HttpResponse.json(page([failed]))),
      http.post(`${API}/admin/tasks/${failed.id}/retry`, () => {
        attempts += 1
        return attempts === 1
          ? HttpResponse.json(errorBody('TASK_ALREADY_ACTIVE', 'x'), { status: 409 })
          : HttpResponse.json({ ...failed, status: 'PENDING' })
      }),
    )
    const { user } = renderApp('/admin/system?tab=tasks')
    const retry = await screen.findByRole('button', { name: /retry résumé processing/i })
    await user.click(retry)
    expect(await screen.findByText(/equivalent task is already running/i)).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /retry résumé processing/i }))
    expect(await screen.findByText(/queued again/i)).toBeInTheDocument()
    expect(attempts).toBe(2)
  })

  it('shows an empty state when there are no tasks', async () => {
    signInAs('ADMIN')
    mockSystem()
    server.use(http.get(`${API}/admin/tasks`, () => HttpResponse.json(page([]))))
    renderApp('/admin/system?tab=tasks')
    expect(await screen.findByText('No background tasks yet')).toBeInTheDocument()
  })
})

describe('system monitoring: models and matching', () => {
  it('shows staleness counts and queues a re-embed', async () => {
    signInAs('ADMIN')
    mockSystem()
    let queued = 0
    server.use(
      http.get(`${API}/admin/embeddings/status`, () =>
        HttpResponse.json(
          makeEmbeddings({
            candidates: { ...makeEmbeddings().candidates, current: 6, outdated: 3, missing: 1 },
          }),
        ),
      ),
      http.get(`${API}/admin/matching/status`, () =>
        HttpResponse.json(makeMatching({ stale_by_version: 12, published_jobs_without_matches: 2 })),
      ),
      http.post(`${API}/admin/embeddings/refresh`, () => {
        queued += 1
        return HttpResponse.json({ task_id: 't-1', status: 'PENDING', created: true }, { status: 202 })
      }),
    )
    const { user } = renderApp('/admin/system?tab=models')
    expect(
      await screen.findByText(/4 item\(s\) are missing an embedding or use another model version/),
    ).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: /Candidate profiles: 6 of 10/ })).toBeInTheDocument()
    expect(screen.getByText('Outdated match scores')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Matching page' })).toHaveAttribute('href', '/matching')
    await user.click(screen.getByRole('button', { name: 'Re-embed stale items' }))
    expect(await screen.findByText('Re-embedding queued')).toBeInTheDocument()
    expect(queued).toBe(1)
  })

  it('disables the action while a refresh is already running', async () => {
    signInAs('ADMIN')
    mockSystem()
    server.use(
      http.get(`${API}/admin/embeddings/status`, () =>
        HttpResponse.json(makeEmbeddings({ active_refresh_task_id: 't-1' })),
      ),
      http.get(`${API}/admin/matching/status`, () => HttpResponse.json(makeMatching())),
    )
    renderApp('/admin/system?tab=models')
    expect(await screen.findByRole('button', { name: 'Re-embedding in progress' })).toBeDisabled()
  })

  it('reports each panel’s error independently', async () => {
    signInAs('ADMIN')
    mockSystem()
    server.use(
      http.get(`${API}/admin/embeddings/status`, () =>
        HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 }),
      ),
      http.get(`${API}/admin/matching/status`, () => HttpResponse.json(makeMatching())),
    )
    renderApp('/admin/system?tab=models')
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    expect(await screen.findByText('Stored pairs')).toBeInTheDocument()
  })
})

describe('system monitoring: audit log', () => {
  it('shows events and sends action, entity and date filters', async () => {
    signInAs('ADMIN')
    mockSystem()
    const seen: URLSearchParams[] = []
    server.use(
      http.get(`${API}/admin/audit`, ({ request }) => {
        seen.push(new URL(request.url).searchParams)
        return HttpResponse.json(
          page([
            makeAudit(),
            makeAudit({
              id: 'a-2',
              action: 'user.registered',
              actor_name: null,
              actor_email: null,
              entity_type: 'user',
              metadata: null,
            }),
          ]),
        )
      }),
    )
    const { user } = renderApp('/admin/system?tab=audit')
    const table = await screen.findByRole('table', { name: /audit events/i })
    expect(within(table).getByText('Riley Recruiter')).toBeInTheDocument()
    expect(within(table).getByText('System')).toBeInTheDocument()
    expect(within(table).getByText('status: DRAFT')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Action'), 'job.*')
    await waitFor(() => expect(seen.at(-1)?.get('action')).toBe('job.*'))
    await user.click(screen.getByRole('combobox', { name: 'Entity' }))
    await user.click(await screen.findByRole('option', { name: 'Job' }))
    await waitFor(() => expect(seen.at(-1)?.get('entity_type')).toBe('job'))
    await user.type(screen.getByLabelText('From'), '2026-10-01')
    await waitFor(() => expect(seen.at(-1)?.get('from_date')).toBe('2026-10-01'))
  })

  it('shows empty and filtered-empty states', async () => {
    signInAs('ADMIN')
    mockSystem()
    server.use(http.get(`${API}/admin/audit`, () => HttpResponse.json(page([]))))
    renderApp('/admin/system?tab=audit&action=nothing.*')
    expect(await screen.findByText('No audit events match these filters')).toBeInTheDocument()
  })
})
