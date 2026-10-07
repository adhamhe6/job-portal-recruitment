import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { notificationHref } from '../lib/links'
import { errorBody, makeNotification, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const bell = () => screen.findByRole('button', { name: /^Notifications/ })

describe('notification bell', () => {
  it('shows the unread count on the bell (and announces it)', async () => {
    signInAs('CANDIDATE')
    server.use(http.get('/api/v1/notifications/unread-count', () => HttpResponse.json({ unread: 3 })))
    renderApp('/dashboard')
    const button = await screen.findByRole('button', { name: 'Notifications, 3 unread' })
    expect(within(button).getByTestId('unread-badge')).toHaveTextContent('3')
  })

  it('caps the badge at 99+ and hides it at zero', async () => {
    signInAs('CANDIDATE')
    server.use(http.get('/api/v1/notifications/unread-count', () => HttpResponse.json({ unread: 120 })))
    const first = renderApp('/dashboard')
    expect(await within(await bell()).findByTestId('unread-badge')).toHaveTextContent('99+')
    first.unmount()

    signInAs('CANDIDATE')
    server.use(http.get('/api/v1/notifications/unread-count', () => HttpResponse.json({ unread: 0 })))
    renderApp('/dashboard')
    const b = await bell()
    await waitFor(() => expect(b).toHaveAccessibleName('Notifications'))
    expect(within(b).queryByTestId('unread-badge')).not.toBeInTheDocument()
  })

  describe('polling', () => {
    afterEach(() => vi.useRealTimers())

    it('re-reads the unread count every 45 seconds', async () => {
      signInAs('CANDIDATE')
      let unread = 1
      let calls = 0
      server.use(
        http.get('/api/v1/notifications/unread-count', () => {
          calls++
          return HttpResponse.json({ unread })
        }),
      )
      vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
      renderApp('/dashboard')
      await screen.findByRole('button', { name: 'Notifications, 1 unread' })
      expect(calls).toBe(1)
      unread = 4
      await vi.advanceTimersByTimeAsync(45_000)
      await screen.findByRole('button', { name: 'Notifications, 4 unread' })
      expect(calls).toBe(2)
    })
  })

  it('opens a dropdown with the latest notifications, marks one read and follows its link', async () => {
    signInAs('CANDIDATE')
    let sizeRequested: string | null = null
    let readId = ''
    server.use(
      http.get('/api/v1/notifications/unread-count', () => HttpResponse.json({ unread: 2 })),
      http.get('/api/v1/notifications', ({ request }) => {
        sizeRequested = new URL(request.url).searchParams.get('page_size')
        return HttpResponse.json(
          page([
            makeNotification({ id: 'n1', title: 'Application update', message: 'Your application was shortlisted.', application_id: 'app-9', job_id: 'job-9' }),
            makeNotification({ id: 'n2', title: 'Old news', is_read: true, type: 'NEW_JOB_RECOMMENDATION', application_id: null, job_id: 'job-3' }),
          ]),
        )
      }),
      http.post('/api/v1/notifications/:id/read', ({ params }) => {
        readId = String(params.id)
        return HttpResponse.json(makeNotification({ id: readId, is_read: true }))
      }),
    )
    const { user, router } = renderApp('/dashboard')
    await user.click(await screen.findByRole('button', { name: 'Notifications, 2 unread' }))
    const popover = await screen.findByRole('dialog')
    expect(await within(popover).findByText('Your application was shortlisted.')).toBeInTheDocument()
    expect(sizeRequested).toBe('8')
    expect(within(popover).getByText('Unread')).toBeInTheDocument() // unread marker is available to screen readers

    await user.click(within(popover).getByRole('link', { name: /Application update/ }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/applications/app-9'))
    expect(readId).toBe('n1')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('"Mark all read" posts once and clears the badge immediately', async () => {
    signInAs('CANDIDATE')
    let unread = 2
    let markAll = 0
    server.use(
      http.get('/api/v1/notifications/unread-count', () => HttpResponse.json({ unread })),
      http.post('/api/v1/notifications/read-all', () => {
        markAll++
        unread = 0
        return HttpResponse.json({ unread: 0 })
      }),
    )
    const { user } = renderApp('/dashboard')
    await user.click(await screen.findByRole('button', { name: 'Notifications, 2 unread' }))
    const popover = await screen.findByRole('dialog')
    await user.click(await within(popover).findByRole('button', { name: /mark all read/i }))
    await waitFor(() => expect(markAll).toBe(1))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument())
    expect(within(popover).getByRole('button', { name: /mark all read/i })).toBeDisabled()
  })

  it('has a friendly empty state and an error state with retry', async () => {
    signInAs('CANDIDATE')
    let fail = true
    server.use(
      http.get('/api/v1/notifications', () => (fail ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'x'), { status: 500 }) : HttpResponse.json(page([])))),
    )
    const { user } = renderApp('/dashboard')
    await user.click(await bell())
    const popover = await screen.findByRole('dialog')
    expect(await within(popover).findByRole('alert')).toBeInTheDocument()
    fail = false
    await user.click(within(popover).getByRole('button', { name: /try again/i }))
    expect(await within(popover).findByText("You're all caught up")).toBeInTheDocument()
  })

  it('the bell is available to staff as well, linking to the full page', async () => {
    signInAs('RECRUITER')
    const { user, router } = renderApp('/dashboard')
    await user.click(await bell())
    await user.click(await screen.findByRole('link', { name: 'View all notifications' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/notifications'))
  })
})

describe('notifications page', () => {
  it('lists notifications with deep links and filters unread through the API', async () => {
    signInAs('CANDIDATE')
    const params: URLSearchParams[] = []
    server.use(
      http.get('/api/v1/notifications', ({ request }) => {
        const p = new URL(request.url).searchParams
        params.push(p)
        const all = [
          makeNotification({ id: 'a', title: 'Interview scheduled', type: 'INTERVIEW_SCHEDULED', interview_id: 'int-1', application_id: 'app-1' }),
          makeNotification({ id: 'b', title: 'Résumé processed', type: 'RESUME_PROCESSED', resume_id: 'r-1', application_id: null, job_id: null, is_read: true }),
        ]
        return HttpResponse.json(page(p.get('unread_only') === 'true' ? all.filter((n) => !n.is_read) : all, { page_size: 15 }))
      }),
    )
    const { user, router } = renderApp('/notifications')
    expect(await screen.findByRole('link', { name: /Interview scheduled/ })).toHaveAttribute('href', '/interviews/int-1')
    expect(screen.getByRole('link', { name: /Résumé processed/ })).toHaveAttribute('href', '/resume')

    await user.click(screen.getByRole('tab', { name: /Unread/ }))
    await waitFor(() => expect(router.state.location.search).toContain('filter=unread'))
    await waitFor(() => expect(params[params.length - 1]!.get('unread_only')).toBe('true'))
    await waitFor(() => expect(screen.queryByRole('link', { name: /Résumé processed/ })).not.toBeInTheDocument())
  })

  it('marks one read when opened, and everything read with the header button', async () => {
    signInAs('CANDIDATE')
    const read: string[] = []
    let all = 0
    server.use(
      http.get('/api/v1/notifications', () => HttpResponse.json(page([makeNotification({ id: 'x1', title: 'First' }), makeNotification({ id: 'x2', title: 'Second' })]))),
      http.post('/api/v1/notifications/:id/read', ({ params }) => {
        read.push(String(params.id))
        return HttpResponse.json(makeNotification({ id: String(params.id), is_read: true }))
      }),
      http.post('/api/v1/notifications/read-all', () => {
        all++
        return HttpResponse.json({ unread: 0 })
      }),
    )
    const { user } = renderApp('/notifications')
    await user.click(await screen.findByRole('link', { name: /First/ }))
    await waitFor(() => expect(read).toEqual(['x1']))
    await user.click(await screen.findByRole('button', { name: 'Mark all as read' }))
    await waitFor(() => expect(all).toBe(1))
  })

  it('paginates', async () => {
    signInAs('CANDIDATE')
    const pages: string[] = []
    server.use(
      http.get('/api/v1/notifications', ({ request }) => {
        pages.push(new URL(request.url).searchParams.get('page') ?? '')
        return HttpResponse.json(page([makeNotification({ title: `Item on page ${pages[pages.length - 1]}` })], { total: 40, pages: 3, page_size: 15 }))
      }),
    )
    const { user, router } = renderApp('/notifications')
    await screen.findByText('Item on page 1')
    await user.click(screen.getByRole('button', { name: 'Next page' }))
    await waitFor(() => expect(router.state.location.search).toContain('page=2'))
    expect(await screen.findByText('Item on page 2')).toBeInTheDocument()
  })

  it('empty states point somewhere useful', async () => {
    signInAs('CANDIDATE')
    server.use(http.get('/api/v1/notifications', () => HttpResponse.json(page([]))))
    renderApp('/notifications')
    expect(await screen.findByRole('heading', { name: 'No notifications yet' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Browse jobs' })).toHaveAttribute('href', '/jobs')
  })
})

describe('notificationHref', () => {
  const base = { job_id: null, application_id: null, interview_id: null, resume_id: null }
  it.each([
    [{ ...base, type: 'INTERVIEW_SCHEDULED' as const, interview_id: 'i1', application_id: 'a1' }, '/interviews/i1'],
    [{ ...base, type: 'APPLICATION_STATUS_CHANGED' as const, application_id: 'a1', job_id: 'j1' }, '/applications/a1'],
    [{ ...base, type: 'APPLICATION_SUBMITTED' as const, application_id: 'a2', job_id: 'j1' }, '/applications/a2'],
    [{ ...base, type: 'NEW_CANDIDATE_MATCH' as const, job_id: 'j1' }, '/matching/j1'],
    [{ ...base, type: 'NEW_JOB_RECOMMENDATION' as const, job_id: 'j7' }, '/jobs/j7'],
    [{ ...base, type: 'RESUME_FAILED' as const, resume_id: 'r1' }, '/resume'],
    [{ ...base, type: 'BULK_IMPORT_COMPLETED' as const }, '/candidates'],
    [{ ...base, type: 'APPLICATION_STATUS_CHANGED' as const }, null],
  ])('%j -> %s', (n, href) => {
    expect(notificationHref(n)).toBe(href)
  })
})
