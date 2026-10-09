import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'
import type { BulkImportBatchDetail } from '../api/bulkImport'
import { chunkFiles, pickFiles } from '../lib/bulkImport'
import { makeCandidateItem } from './testData'

const file = (name: string, size = 1000, type = 'application/pdf') => {
  const f = new File(['x'.repeat(Math.min(size, 10))], name, { type })
  Object.defineProperty(f, 'size', { value: size })
  return f
}

describe('bulk import file helpers', () => {
  it('accepts PDF/DOCX and explains why anything else is refused', () => {
    const r = pickFiles(
      [file('dup.pdf', 500)],
      [
        file('a.pdf'),
        file('b.DOCX'),
        file('c.zip', 10, 'application/zip'),
        file('d.doc'),
        file('big.pdf', 6 * 1024 * 1024),
        file('empty.pdf', 0),
        file('dup.pdf', 500),
      ],
    )
    expect(r.accepted.map((f) => f.name)).toEqual(['a.pdf', 'b.DOCX'])
    const reasons = Object.fromEntries(r.problems.map((p) => [p.name, p.reason]))
    expect(reasons['c.zip']).toMatch(/ZIP archives are not supported/)
    expect(reasons['d.doc']).toMatch(/Only PDF and DOCX/)
    expect(reasons['big.pdf']).toMatch(/Larger than 5 MB/)
    expect(reasons['empty.pdf']).toMatch(/empty/)
    expect(reasons['dup.pdf']).toMatch(/Already in the list/)
  })

  it('splits big selections into request-sized groups', () => {
    const mb = 1024 * 1024
    const files = [file('1.pdf', 4 * mb), file('2.pdf', 4 * mb), file('3.pdf', 4 * mb), file('4.pdf', mb)]
    const chunks = chunkFiles(files, 10 * mb)
    expect(chunks.map((c) => c.map((f) => f.name))).toEqual([
      ['1.pdf', '2.pdf'],
      ['3.pdf', '4.pdf'],
    ])
  })
})

function batch(overrides: Partial<BulkImportBatchDetail> = {}): BulkImportBatchDetail {
  return {
    id: 'batch-1',
    status: 'RUNNING',
    total_files: 3,
    counts: { pending: 1, created: 1, duplicate: 0, failed: 1 },
    task_id: 'task-1',
    progress: 66,
    created_at: new Date().toISOString(),
    finished_at: null,
    items: [
      { id: 'i1', filename: 'ada.pdf', size_bytes: 2048, status: 'CREATED', candidate_id: 'cand-new' },
      {
        id: 'i2',
        filename: 'scan.pdf',
        size_bytes: 4096,
        status: 'FAILED',
        error_code: 'NO_TEXT',
        error_message: 'No readable text found; the file looks like a scan.',
      },
      { id: 'i3', filename: 'bob.docx', size_bytes: 1024, status: 'PENDING' },
    ],
    ...overrides,
  }
}

function setup(opts: { accepted?: object; polls?: BulkImportBatchDetail[] } = {}) {
  signInAs('RECRUITER')
  const uploads: FormData[] = []
  const polls = [...(opts.polls ?? [batch()])]
  const searchCalls = { n: 0 }
  server.use(
    http.get('/api/v1/search/candidates', () => {
      searchCalls.n++
      return HttpResponse.json(page([makeCandidateItem()]))
    }),
    http.get('/api/v1/jobs', () => HttpResponse.json(page([makeJobListItem()]))),
    http.get('/api/v1/resumes/bulk-imports', () => HttpResponse.json(page([]))),
    http.post('/api/v1/resumes/bulk-imports', async ({ request }) => {
      uploads.push(await request.formData())
      return HttpResponse.json(
        opts.accepted ?? {
          batch_id: 'batch-1',
          task_id: 'task-1',
          accepted: 3,
          rejected: [
            {
              filename: 'old-cv.doc',
              reason: 'Legacy Word (.doc) files are not supported.',
              code: 'UNSUPPORTED_MEDIA_TYPE',
            },
          ],
          message: null,
        },
        { status: 202 },
      )
    }),
    http.get('/api/v1/resumes/bulk-imports/batch-1', () =>
      HttpResponse.json(polls.length > 1 ? polls.shift() : polls[0]),
    ),
  )
  return { uploads, searchCalls }
}

async function openDialog(user: ReturnType<typeof renderApp>['user']) {
  await screen.findByText('Priya Nair')
  await user.click(screen.getByRole('button', { name: /Bulk résumé import/ }))
  return screen.findByRole('dialog', { name: 'Bulk résumé import' })
}
const choose = (dialog: HTMLElement, files: File[]) =>
  fireEvent.change(dialog.querySelector('input[type=file]')!, { target: { files } })

describe('bulk résumé import dialog', () => {
  it('uploads the chosen files, reports server rejections and follows the batch until it finishes', async () => {
    const { uploads, searchCalls } = setup({
      polls: [
        batch(),
        batch({
          status: 'COMPLETED',
          progress: 100,
          counts: { pending: 0, created: 2, duplicate: 0, failed: 1 },
          finished_at: new Date().toISOString(),
          items: [
            { id: 'i1', filename: 'ada.pdf', size_bytes: 2048, status: 'CREATED', candidate_id: 'cand-new' },
            {
              id: 'i2',
              filename: 'scan.pdf',
              size_bytes: 4096,
              status: 'FAILED',
              error_message: 'No readable text found; the file looks like a scan.',
            },
            { id: 'i3', filename: 'bob.docx', size_bytes: 1024, status: 'CREATED', candidate_id: 'cand-bob' },
          ],
        }),
      ],
    })
    const { user } = renderApp('/candidates')
    const dialog = await openDialog(user)
    const before = searchCalls.n
    choose(dialog, [
      file('ada.pdf'),
      file('scan.pdf'),
      file('bob.docx', 1024, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
      file('old-cv.doc'),
    ])
    // old-cv.doc is refused locally with a reason; the other three are listed
    expect(within(dialog).getByText(/1 file not added/)).toBeInTheDocument()
    expect(within(dialog).getByText('3 files selected', { exact: false })).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: /Import 3 résumés/ }))

    await waitFor(() => expect(uploads).toHaveLength(1))
    expect(uploads[0]!.getAll('files')).toHaveLength(3)
    expect(await within(dialog).findByText('1 file rejected by the server')).toBeInTheDocument()
    expect(within(dialog).getByText(/Legacy Word \(\.doc\) files are not supported/)).toBeInTheDocument()

    // running: per-file outcomes with reasons
    const files = await within(dialog).findByRole('list', { name: 'Files in this import' })
    expect(within(files).getByText(/No readable text found/)).toBeInTheDocument()
    expect(within(files).getByText('Waiting', { exact: false })).toBeInTheDocument()
    expect(within(dialog).getByRole('progressbar', { name: 'Import progress' })).toHaveAttribute(
      'aria-valuenow',
      '66',
    )

    // polling moves on to COMPLETED, and the candidate search is refreshed
    await within(dialog).findByText('Finished', undefined, { timeout: 6000 })
    expect(within(dialog).getByText(/2 imported · 0 duplicates · 1 failed/)).toBeInTheDocument()
    expect(within(files).getAllByRole('link', { name: /View profile/ })).toHaveLength(2)
    await waitFor(() => expect(searchCalls.n).toBeGreaterThan(before))
  }, 15000)

  it('lets the recruiter re-queue a batch whose task never started', async () => {
    setup({
      accepted: {
        batch_id: 'batch-1',
        task_id: null,
        accepted: 1,
        rejected: [],
        message: 'Queue unavailable',
      },
      polls: [
        batch({
          status: 'PENDING',
          task_id: null,
          progress: 0,
          counts: { pending: 1, created: 0, duplicate: 0, failed: 0 },
          total_files: 1,
          items: [{ id: 'i3', filename: 'bob.docx', size_bytes: 1024, status: 'PENDING' }],
        }),
      ],
    })
    let reprocessed = false
    server.use(
      http.post('/api/v1/resumes/bulk-imports/batch-1/process', () => {
        reprocessed = true
        return HttpResponse.json({ task_id: 't2' }, { status: 202 })
      }),
    )
    const { user } = renderApp('/candidates')
    const dialog = await openDialog(user)
    choose(dialog, [file('bob.pdf')])
    await user.click(within(dialog).getByRole('button', { name: /Import 1 résumé/ }))
    await user.click(await within(dialog).findByRole('button', { name: 'Retry processing' }))
    await waitFor(() => expect(reprocessed).toBe(true))
  })

  it('shows duplicates with their reason and a link to the existing candidate', async () => {
    setup({
      polls: [
        batch({
          status: 'COMPLETED',
          progress: 100,
          total_files: 1,
          counts: { pending: 0, created: 0, duplicate: 1, failed: 0 },
          items: [
            {
              id: 'd1',
              filename: 'priya.pdf',
              size_bytes: 900,
              status: 'DUPLICATE',
              candidate_id: 'cand-1',
              error_code: 'DUPLICATE_CANDIDATE',
              error_message: null,
            },
          ],
        }),
      ],
    })
    const { user } = renderApp('/candidates')
    const dialog = await openDialog(user)
    choose(dialog, [file('priya.pdf')])
    await user.click(within(dialog).getByRole('button', { name: /Import 1 résumé/ }))
    expect(
      await within(dialog).findByText(/A candidate with this e-mail address already exists/),
    ).toBeInTheDocument()
    expect(within(dialog).getByRole('link', { name: /View existing/ })).toHaveAttribute(
      'href',
      '/candidates/cand-1',
    )
  })

  it('keeps the selection and explains an upload failure (rate limit)', async () => {
    setup()
    server.use(
      http.post('/api/v1/resumes/bulk-imports', () =>
        HttpResponse.json(errorBody('RATE_LIMITED', 'slow down'), { status: 429 }),
      ),
    )
    const { user } = renderApp('/candidates')
    const dialog = await openDialog(user)
    choose(dialog, [file('a.pdf')])
    await user.click(within(dialog).getByRole('button', { name: /Import 1 résumé/ }))
    expect(await within(dialog).findByText(/Too many uploads/)).toBeInTheDocument()
    expect(within(dialog).getByText('a.pdf')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /Import 1 résumé/ })).toBeEnabled()
  })

  it('lists earlier imports and opens one', async () => {
    setup()
    server.use(
      http.get('/api/v1/resumes/bulk-imports', () =>
        HttpResponse.json(
          page([
            {
              id: 'batch-1',
              status: 'COMPLETED',
              total_files: 4,
              counts: { pending: 0, created: 3, duplicate: 0, failed: 1 },
              created_at: new Date().toISOString(),
            },
          ]),
        ),
      ),
    )
    const { user } = renderApp('/candidates')
    const dialog = await openDialog(user)
    const recent = await within(dialog).findByRole('list', { name: 'Recent imports' })
    expect(within(recent).getByText(/3 imported, 1 failed/)).toBeInTheDocument()
    await user.click(within(recent).getByRole('button', { name: 'View details' }))
    expect(await within(dialog).findByRole('list', { name: 'Files in this import' })).toBeInTheDocument()
  })
})
