import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, makeJobPublic } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const RESUMES = [
  { id: 'r1', original_filename: 'alex-cv.pdf', is_primary: true, created_at: '2026-09-01T00:00:00Z' },
  {
    id: 'r2',
    original_filename: 'alex-cv-short.docx',
    is_primary: false,
    created_at: '2026-09-10T00:00:00Z',
  },
]

function setup({ resumes = RESUMES as unknown } = {}) {
  const list = resumes as Record<string, unknown>[]
  signInAs('CANDIDATE')
  server.use(
    http.get('/api/v1/jobs/:id', () => HttpResponse.json(makeJobPublic({ id: 'job-1', can_apply: true }))),
    http.get('/api/v1/matches/me/jobs/:id', () =>
      HttpResponse.json(errorBody('NOT_FOUND', 'no match'), { status: 404 }),
    ),
    http.get('/api/v1/resumes', () =>
      resumes === 404
        ? HttpResponse.json(errorBody('NOT_FOUND', 'Not Found'), { status: 404 })
        : HttpResponse.json(list),
    ),
  )
  return renderApp('/jobs/job-1')
}

const openDialog = async (user: ReturnType<typeof renderApp>['user']) => {
  await user.click(await screen.findByRole('button', { name: /apply now/i }))
  return screen.findByRole('dialog', { name: /apply to senior backend engineer/i })
}

describe('apply dialog', () => {
  it('submits the chosen résumé and cover letter, then confirms', async () => {
    let body: unknown
    server.use(
      http.post('/api/v1/applications', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ id: 'app-1', status: 'APPLIED' }, { status: 201 })
      }),
    )
    const { user } = setup()
    const dialog = await openDialog(user)
    // the primary résumé is preselected
    expect(await within(dialog).findByRole('radio', { name: /alex-cv\.pdf/ })).toBeChecked()
    await user.click(within(dialog).getByRole('radio', { name: /alex-cv-short\.docx/ }))
    await user.type(within(dialog).getByLabelText(/cover letter/i), 'I would love to join.')
    await user.click(within(dialog).getByRole('button', { name: 'Submit application' }))
    await waitFor(() =>
      expect(body).toEqual({
        job_id: 'job-1',
        resume_id: 'r2',
        cover_letter: 'I would love to join.',
        source: 'DIRECT',
      }),
    )
    expect(await screen.findByText(/Application sent to Northwind Labs/)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('uses the primary résumé by default and sends no cover letter when empty', async () => {
    let body: Record<string, unknown> = {}
    server.use(
      http.post('/api/v1/applications', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'app-1' }, { status: 201 })
      }),
    )
    const { user } = setup()
    const dialog = await openDialog(user)
    await within(dialog).findByRole('radio', { name: /alex-cv\.pdf/ })
    await user.click(within(dialog).getByRole('button', { name: 'Submit application' }))
    await waitFor(() => expect(body.resume_id).toBe('r1'))
    expect(body.cover_letter).toBeNull()
  })

  it.each([
    ['endpoint unavailable (404)', 404 as unknown],
    ['empty list', [] as unknown],
  ])(
    'guides the candidate to upload a résumé first (%s) but still allows applying',
    async (_name, resumes) => {
      let body: Record<string, unknown> = {}
      server.use(
        http.post('/api/v1/applications', async ({ request }) => {
          body = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({ id: 'app-1' }, { status: 201 })
        }),
      )
      const { user } = setup({ resumes })
      const dialog = await openDialog(user)
      expect(await within(dialog).findByText('Upload a résumé first')).toBeInTheDocument()
      expect(within(dialog).getByRole('link', { name: 'Upload your résumé' })).toHaveAttribute(
        'href',
        '/resume',
      )
      await user.click(within(dialog).getByRole('button', { name: 'Submit application' }))
      await waitFor(() => expect(body.resume_id).toBeNull())
    },
  )

  it('explains a duplicate application (409 APPLICATION_ALREADY_EXISTS)', async () => {
    server.use(
      http.post('/api/v1/applications', () =>
        HttpResponse.json(errorBody('APPLICATION_ALREADY_EXISTS', 'You have already applied to this job.'), {
          status: 409,
        }),
      ),
    )
    const { user } = setup()
    const dialog = await openDialog(user)
    await within(dialog).findByRole('radio', { name: /alex-cv\.pdf/ })
    await user.click(within(dialog).getByRole('button', { name: 'Submit application' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('You have already applied to this job')
    expect(within(alert).getByRole('link', { name: 'View my applications' })).toHaveAttribute(
      'href',
      '/applications',
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument() // stays open so the message can be read
  })

  it('explains a closed job (422 JOB_NOT_ACCEPTING_APPLICATIONS)', async () => {
    server.use(
      http.post('/api/v1/applications', () =>
        HttpResponse.json(
          errorBody('JOB_NOT_ACCEPTING_APPLICATIONS', 'The application deadline has passed'),
          { status: 422 },
        ),
      ),
    )
    const { user } = setup()
    const dialog = await openDialog(user)
    await within(dialog).findByRole('radio', { name: /alex-cv\.pdf/ })
    await user.click(within(dialog).getByRole('button', { name: 'Submit application' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'The application deadline has passed. This job can no longer be applied to.',
    )
  })

  it('closes with Escape and returns focus to the trigger', async () => {
    const { user } = setup()
    const trigger = await screen.findByRole('button', { name: /apply now/i })
    await user.click(trigger)
    await screen.findByRole('dialog')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
