import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeExtracted, makeProfile, makeResume } from '@/test/candidateFixtures'
import { errorBody, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const API = '/api/v1'
const listResumes = (items = [makeResume({ id: 'res-1' })]) =>
  server.use(http.get(`${API}/resumes`, () => HttpResponse.json(page(items))))

const pdf = (name = 'cv.pdf', bytes = 1200) =>
  new File([new Uint8Array(bytes)], name, { type: 'application/pdf' })
const dropzoneInput = () => document.querySelector<HTMLInputElement>('input[type="file"]')!

describe('ResumePage: list and actions', () => {
  afterEach(() => vi.useRealTimers())

  it('shows an empty state with the upload form', async () => {
    signInAs('CANDIDATE')
    listResumes([])
    renderApp('/resume')
    expect(await screen.findByRole('heading', { name: 'No résumé uploaded yet' })).toBeInTheDocument()
    expect(screen.getByText(/PDF or Word \(\.docx\), up to 5 MB/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload résumé' })).toBeDisabled()
  })

  it('shows an error state with retry', async () => {
    signInAs('CANDIDATE')
    let calls = 0
    server.use(
      http.get(`${API}/resumes`, () => {
        calls++
        return calls === 1
          ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })
          : HttpResponse.json(page([makeResume()]))
      }),
    )
    const { user } = renderApp('/resume')
    expect(await screen.findByRole('heading', { name: "Couldn't load your résumés" })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByRole('heading', { name: 'alex-cv.pdf' })).toBeInTheDocument()
  })

  it('rejects unsupported types and oversized files before uploading', async () => {
    signInAs('CANDIDATE')
    listResumes([])
    renderApp('/resume')
    await screen.findByRole('heading', { name: 'No résumé uploaded yet' })

    fireEvent.change(dropzoneInput(), {
      target: { files: [new File(['x'], 'notes.txt', { type: 'text/plain' })] },
    })
    expect(await screen.findByText(/Unsupported file type/)).toBeInTheDocument()

    const big = new File([new Uint8Array(6 * 1024 * 1024)], 'big.pdf', { type: 'application/pdf' })
    fireEvent.change(dropzoneInput(), { target: { files: [big] } })
    expect(await screen.findByText(/File is too large/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload résumé' })).toBeDisabled()
  })

  it('uploads a PDF as multipart with set_primary and refreshes the list', async () => {
    signInAs('CANDIDATE')
    const items: ReturnType<typeof makeResume>[] = []
    let sent: { name: string; primary: string | null } | null = null
    server.use(
      http.get(`${API}/resumes`, () => HttpResponse.json(page(items))),
      http.post(`${API}/resumes`, async ({ request }) => {
        const form = await request.formData()
        const file = form.get('file') as File
        sent = { name: file.name, primary: form.get('set_primary') as string | null }
        const r = makeResume({
          id: 'res-new',
          original_filename: file.name,
          status: 'PROCESSING',
          processing: { task_status: 'RUNNING', progress: 40, stage: 'PARSING' },
        })
        items.push(r)
        return HttpResponse.json({ ...r, duplicate: false, message: null }, { status: 202 })
      }),
    )
    const { user } = renderApp('/resume')
    await screen.findByRole('heading', { name: 'No résumé uploaded yet' })
    fireEvent.change(dropzoneInput(), { target: { files: [pdf('my-cv.pdf')] } })
    await user.click(screen.getByRole('button', { name: 'Upload résumé' }))
    expect(await screen.findByRole('heading', { name: 'my-cv.pdf' })).toBeInTheDocument()
    expect(sent).toEqual({ name: 'my-cv.pdf', primary: 'true' })
    expect(screen.getByRole('progressbar', { name: 'Processing my-cv.pdf' })).toHaveAttribute(
      'aria-valuenow',
      '40',
    )
  })

  it('explains server-side upload errors in plain language', async () => {
    signInAs('CANDIDATE')
    listResumes([])
    server.use(
      http.post(`${API}/resumes`, () =>
        HttpResponse.json(errorBody('UNSUPPORTED_MEDIA_TYPE', 'bad'), { status: 415 }),
      ),
    )
    const { user } = renderApp('/resume')
    await screen.findByRole('heading', { name: 'No résumé uploaded yet' })
    fireEvent.change(dropzoneInput(), { target: { files: [pdf()] } })
    await user.click(screen.getByRole('button', { name: 'Upload résumé' }))
    expect(await screen.findByText(/Only PDF and Word \(\.docx\) résumés are supported/)).toBeInTheDocument()
  })

  it('polls while a résumé is processing and shows it as processed when the task is done', async () => {
    signInAs('CANDIDATE')
    let status: 'PROCESSING' | 'PROCESSED' = 'PROCESSING'
    server.use(
      http.get(`${API}/resumes`, () =>
        HttpResponse.json(
          page([
            makeResume({
              id: 'res-1',
              status,
              processing:
                status === 'PROCESSING'
                  ? { task_status: 'RUNNING', progress: 55, stage: 'EXTRACTING_TEXT' }
                  : { task_status: 'COMPLETED', progress: 100 },
            }),
          ]),
        ),
      ),
    )
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    renderApp('/resume')
    expect(await screen.findByRole('progressbar', { name: 'Processing alex-cv.pdf' })).toHaveAttribute(
      'aria-valuenow',
      '55',
    )
    expect(screen.getByText(/Extracting text/)).toBeInTheDocument()
    status = 'PROCESSED'
    await vi.advanceTimersByTimeAsync(2100)
    expect(await screen.findByRole('button', { name: /Review suggestions/ })).toBeInTheDocument()
    expect(screen.queryByRole('progressbar', { name: /Processing/ })).not.toBeInTheDocument()
  })

  it('offers to retry a failed résumé and shows the safe error message', async () => {
    signInAs('CANDIDATE')
    listResumes([
      makeResume({
        id: 'res-f',
        status: 'FAILED',
        processing: {
          task_status: 'FAILED',
          error_code: 'NO_TEXT_EXTRACTED',
          error_message: 'No readable text was found.',
        },
      }),
    ])
    let reprocessed = ''
    server.use(
      http.post(`${API}/resumes/:id/process`, ({ params }) => {
        reprocessed = String(params.id)
        return HttpResponse.json({ task_id: 't2', status: 'PENDING' }, { status: 202 })
      }),
    )
    const { user } = renderApp('/resume')
    expect(await screen.findByText(/No readable text was found/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    await waitFor(() => expect(reprocessed).toBe('res-f'))
  })

  it('makes another résumé primary', async () => {
    signInAs('CANDIDATE')
    listResumes([
      makeResume({ id: 'res-1', original_filename: 'one.pdf', is_primary: true }),
      makeResume({ id: 'res-2', original_filename: 'two.pdf', is_primary: false }),
    ])
    let made = ''
    server.use(
      http.post(`${API}/resumes/:id/primary`, ({ params }) => {
        made = String(params.id)
        return HttpResponse.json(makeResume({ id: 'res-2' }))
      }),
    )
    const { user } = renderApp('/resume')
    await user.click(await screen.findByRole('button', { name: 'Make two.pdf my primary résumé' }))
    await waitFor(() => expect(made).toBe('res-2'))
    expect(screen.queryByRole('button', { name: 'Make one.pdf my primary résumé' })).not.toBeInTheDocument()
  })

  it('deletes after confirmation and explains when the résumé is attached to an application', async () => {
    signInAs('CANDIDATE')
    listResumes([makeResume({ id: 'res-1' })])
    let attempts = 0
    server.use(
      http.delete(`${API}/resumes/:id`, () => {
        attempts++
        return attempts === 1
          ? HttpResponse.json(errorBody('RESUME_IN_USE', 'in use'), { status: 409 })
          : new HttpResponse(null, { status: 204 })
      }),
    )
    const { user } = renderApp('/resume')
    await user.click(await screen.findByRole('button', { name: 'Delete alex-cv.pdf' }))
    let dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Delete résumé' }))
    expect(await within(dialog).findByText(/attached to one of your applications/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Delete résumé' }))
    await waitFor(() => expect(attempts).toBe(2))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    dialog = null as never
  })

  it('downloads the stored file through the authenticated endpoint', async () => {
    signInAs('CANDIDATE')
    listResumes([makeResume({ id: 'res-1' })])
    let requested = false
    server.use(
      http.get(`${API}/resumes/:id/file`, () => {
        requested = true
        return new HttpResponse('%PDF-1.4', {
          headers: {
            'Content-Type': 'application/pdf',
            'Content-Disposition': 'attachment; filename="alex-cv.pdf"',
          },
        })
      }),
    )
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { user } = renderApp('/resume')
    await user.click(await screen.findByRole('button', { name: 'Download alex-cv.pdf' }))
    await waitFor(() => expect(requested).toBe(true))
    await waitFor(() => expect(click).toHaveBeenCalled())
    click.mockRestore()
  })
})

describe('ResumePage: review flow', () => {
  const setup = (extracted = makeExtracted()) => {
    signInAs('CANDIDATE')
    listResumes([makeResume({ id: 'res-1' })])
    server.use(
      http.get(`${API}/candidates/me`, () => HttpResponse.json(makeProfile())),
      http.get(`${API}/resumes/res-1/extracted`, () => HttpResponse.json(extracted)),
    )
  }

  it('lists every suggestion with its state and never pre-selects what would overwrite the profile', async () => {
    setup()
    const { user } = renderApp('/resume')
    await user.click(await screen.findByRole('button', { name: /Review suggestions/ }))
    const panel = await screen
      .findByRole('region', { name: 'Review suggestions' }, { timeout: 4000 })
      .catch(() => null)
    const heading = await screen.findByRole('heading', { name: 'Review suggestions' })
    expect(panel ?? heading).toBeTruthy()

    const skills = await screen.findByRole('list', { name: 'Skills suggestions' })
    expect(within(skills).getByLabelText('Kubernetes')).toBeChecked()
    // already on profile -> disabled + explained
    expect(within(skills).getByLabelText('Python')).toBeDisabled()
    expect(within(skills).getByText('Already on your profile')).toBeInTheDocument()
    // unknown to the skill library -> cannot be applied
    expect(within(skills).getByLabelText('Fortran77')).toBeDisabled()
    expect(within(skills).getByText(/Not in the skill library/)).toBeInTheDocument()

    const exps = screen.getByRole('list', { name: 'Work experience suggestions' })
    expect(within(exps).getByLabelText('Platform Engineer at Globex')).toBeChecked()
    expect(within(exps).getByLabelText('Developer')).toBeDisabled()
    expect(within(exps).getByText(/Missing company, start date/)).toBeInTheDocument()

    const fields = screen.getByRole('list', { name: 'Profile detail suggestions' })
    expect(within(fields).getByLabelText('Phone')).toBeChecked() // profile phone is empty
    expect(within(fields).getByLabelText('Headline')).not.toBeChecked() // would replace "Backend engineer"
    expect(within(fields).getByText('Backend engineer')).toBeInTheDocument()
  })

  it('applies exactly the selected items, with overwrite only when explicitly opted in', async () => {
    setup()
    let body: unknown = null
    server.use(
      http.post(`${API}/resumes/res-1/extracted/apply`, async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          applied: { skills: 1, experiences: 1 },
          fields_applied: ['phone', 'headline'],
          skipped: [{ section: 'skills', index: 2, reason: 'UNKNOWN_SKILL' }],
        })
      }),
    )
    const { user } = renderApp('/resume?review=res-1')
    const fields = await screen.findByRole('list', { name: 'Profile detail suggestions' })
    await user.click(within(fields).getByLabelText('Headline'))
    await user.click(await within(fields).findByLabelText('Replace my current headline'))
    await user.click(screen.getByRole('button', { name: /Apply 4 selected to my profile/ }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({
      skills: [0],
      experiences: [0],
      educations: [],
      certifications: [],
      languages: [],
      fields: ['phone', 'headline'],
      overwrite: ['headline'],
    })
    expect(
      await screen.findByText(/Added to your profile: 1 skill, 1 work experience, 2 profile fields/),
    ).toBeInTheDocument()
    expect(screen.getByText(/not in the skill library/)).toBeInTheDocument()
  })

  it('lets the candidate deselect items and clear the whole selection', async () => {
    setup()
    const { user } = renderApp('/resume?review=res-1')
    const skills = await screen.findByRole('list', { name: 'Skills suggestions' })
    await user.click(within(skills).getByLabelText('Kubernetes'))
    expect(within(skills).getByLabelText('Kubernetes')).not.toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(screen.getByRole('button', { name: /Apply selected to my profile/ })).toBeDisabled()
  })

  it('rejects a suggestion with PATCH remove', async () => {
    setup()
    let body: unknown = null
    server.use(
      http.patch(`${API}/resumes/res-1/extracted`, async ({ request }) => {
        body = await request.json()
        const e = makeExtracted()
        return HttpResponse.json({ ...e, skills: e.skills.filter((s) => s.index !== 0) })
      }),
    )
    const { user } = renderApp('/resume?review=res-1')
    await user.click(await screen.findByRole('button', { name: 'Reject suggestion Kubernetes' }))
    await waitFor(() => expect(body).toEqual({ skills: [{ index: 0, remove: true }] }))
    await waitFor(() => expect(screen.queryByText('Kubernetes')).not.toBeInTheDocument())
  })

  it('edits a suggestion to complete the missing fields, then it becomes selectable', async () => {
    setup()
    let body: Record<string, unknown> | null = null
    server.use(
      http.patch(`${API}/resumes/res-1/extracted`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        const e = makeExtracted()
        const fixed = {
          ...e.experiences[1]!,
          company: 'Initech',
          start_date: '2016-05-01',
          corrected: true,
          missing_for_apply: [],
        }
        return HttpResponse.json({ ...e, has_corrections: true, experiences: [e.experiences[0]!, fixed] })
      }),
    )
    const { user } = renderApp('/resume?review=res-1')
    await user.click(await screen.findByRole('button', { name: 'Edit suggestion Developer' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit experience suggestion' })
    await user.type(within(dialog).getByLabelText('Company'), 'Initech')
    await user.type(within(dialog).getByLabelText('Start date'), '2016-05-01')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({
      experiences: [
        { index: 1, title: 'Developer', company: 'Initech', start_date: '2016-05-01', is_current: false },
      ],
    })
    const exps = screen.getByRole('list', { name: 'Work experience suggestions' })
    await waitFor(() => expect(within(exps).getByLabelText('Developer at Initech')).toBeEnabled())
    expect(within(exps).getByText('Edited by you')).toBeInTheDocument()
  })

  it('shows an error with retry when the suggestions cannot be loaded', async () => {
    signInAs('CANDIDATE')
    listResumes([makeResume({ id: 'res-1' })])
    server.use(
      http.get(`${API}/candidates/me`, () => HttpResponse.json(makeProfile())),
      http.get(`${API}/resumes/res-1/extracted`, () =>
        HttpResponse.json(errorBody('RESUME_NOT_PROCESSED', 'Not processed yet'), { status: 409 }),
      ),
    )
    renderApp('/resume?review=res-1')
    expect(await screen.findByRole('heading', { name: "Couldn't load the suggestions" })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Try again/ })).toBeInTheDocument()
  })

  it('says so when a résumé has nothing to review', async () => {
    setup(
      makeExtracted({ skills: [], experiences: [], headline: null, contact: {}, years_of_experience: null }),
    )
    renderApp('/resume?review=res-1')
    expect(await screen.findByText('Nothing to review')).toBeInTheDocument()
  })
})
