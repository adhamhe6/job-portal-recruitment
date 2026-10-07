import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const withJobs = (items = [makeJobListItem({ id: 'job-1', title: 'Backend Engineer', is_saved: false })]) =>
  server.use(http.get('/api/v1/search/jobs', () => HttpResponse.json(page(items))))

describe('save / unsave toggle', () => {
  it('saves optimistically and calls PUT /jobs/:id/save', async () => {
    signInAs('CANDIDATE')
    withJobs()
    let release: () => void = () => {}
    const gate = new Promise<void>((r) => (release = r))
    let called = ''
    server.use(
      http.put('/api/v1/jobs/:id/save', async ({ params }) => {
        called = `PUT ${String(params.id)}`
        await gate
        return HttpResponse.json({ message: 'Saved' })
      }),
    )
    const { user } = renderApp('/jobs')
    const heart = await screen.findByRole('button', { name: 'Save Backend Engineer' })
    expect(heart).toHaveAttribute('aria-pressed', 'false')
    await user.click(heart)
    // optimistic: flipped before the server answered
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Remove Backend Engineer from saved jobs' })).toHaveAttribute(
        'aria-pressed',
        'true',
      ),
    )
    release()
    await waitFor(() => expect(called).toBe('PUT job-1'))
  })

  it('unsaves with DELETE and rolls back if the server rejects', async () => {
    signInAs('CANDIDATE')
    withJobs([makeJobListItem({ id: 'job-1', title: 'Backend Engineer', is_saved: true })])
    server.use(
      http.delete('/api/v1/jobs/:id/save', () =>
        HttpResponse.json(errorBody('INTERNAL_ERROR', 'nope'), { status: 500 }),
      ),
    )
    const { user } = renderApp('/jobs')
    const heart = await screen.findByRole('button', { name: 'Remove Backend Engineer from saved jobs' })
    expect(heart).toHaveAttribute('aria-pressed', 'true')
    await user.click(heart)
    // rolled back after the failure
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Remove Backend Engineer from saved jobs' })).toHaveAttribute(
        'aria-pressed',
        'true',
      ),
    )
    expect(await screen.findByText('Could not remove the job')).toBeInTheDocument()
  })

  it('visitors get a "sign in to save" link that returns them to the same page', async () => {
    withJobs()
    renderApp('/jobs?q=backend')
    const link = await screen.findByRole('link', { name: 'Sign in to save Backend Engineer' })
    expect(link).toHaveAttribute('href', `/login?next=${encodeURIComponent('/jobs?q=backend')}`)
  })

  it('recruiters do not see a save heart', async () => {
    signInAs('RECRUITER')
    withJobs()
    renderApp('/jobs')
    await screen.findByText('Backend Engineer')
    expect(screen.queryByRole('button', { name: /^Save / })).not.toBeInTheDocument()
  })
})

describe('Saved jobs page', () => {
  it('lists saved jobs and removes a job from the list when it is unsaved', async () => {
    signInAs('CANDIDATE')
    const saved = new Set(['job-1', 'job-2'])
    server.use(
      http.get('/api/v1/candidates/me/saved-jobs', () =>
        HttpResponse.json(
          page(
            [...saved].map((id) =>
              makeJobListItem({
                id,
                title: id === 'job-1' ? 'Saved Job One' : 'Saved Job Two',
                is_saved: true,
              }),
            ),
          ),
        ),
      ),
      http.delete('/api/v1/jobs/:id/save', ({ params }) => {
        saved.delete(String(params.id))
        return HttpResponse.json({ message: 'Removed' })
      }),
    )
    const { user } = renderApp('/jobs/saved')
    const first = (await screen.findByRole('heading', { name: 'Saved Job One' })).closest('article')!
    await user.click(within(first).getByRole('button', { name: /Remove Saved Job One from saved jobs/ }))
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Saved Job One' })).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('heading', { name: 'Saved Job Two' })).toBeInTheDocument()
  })

  it('shows a helpful empty state', async () => {
    signInAs('CANDIDATE')
    server.use(http.get('/api/v1/candidates/me/saved-jobs', () => HttpResponse.json(page([]))))
    renderApp('/jobs/saved')
    expect(await screen.findByRole('heading', { name: 'No saved jobs yet' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Browse jobs' })).toHaveAttribute('href', '/jobs')
  })
})
