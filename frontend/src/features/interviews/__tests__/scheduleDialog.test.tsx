import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { COMPANY_ID, errorBody } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderWithProviders, signInAs } from '@/test/test-utils'
import type { StaffInterviewItem, StaffInterviewView } from '../api/types'
import { ScheduleInterviewDialog } from '../components/ScheduleInterviewDialog'
import { conflictBody, makeMember, makeStaffView } from './fixtures'

const API = '/api/v1'

const application = (status = 'SHORTLISTED') => ({
  id: 'app-1',
  job_id: 'job-1',
  job_title: 'Senior Backend Engineer',
  company_id: COMPANY_ID,
  company_name: 'Northwind Labs',
  candidate_id: 'cand-9',
  candidate_name: 'Nina Petrova',
  status,
})

function mockContext(status = 'SHORTLISTED') {
  server.use(
    http.get(`${API}/applications/app-1`, () => HttpResponse.json(application(status))),
    http.get(`${API}/jobs/job-1`, () => HttpResponse.json({ id: 'job-1', hiring_manager_id: 'user-hannah' })),
    http.get(`${API}/companies/${COMPANY_ID}/members`, () =>
      HttpResponse.json([
        makeMember('user-recruiter', 'Riley'),
        makeMember('user-ravi', 'Ravi'),
        makeMember('user-hannah', 'Hannah', 'HIRING_MANAGER'),
        makeMember('user-other-hm', 'Otto', 'HIRING_MANAGER'),
        { ...makeMember('user-gone', 'Gone'), status: 'SUSPENDED' },
      ]),
    ),
  )
}

function Harness({
  interview,
  onDone,
}: {
  interview?: StaffInterviewItem | StaffInterviewView
  onDone?: (i: StaffInterviewView) => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <>
      <p>{open ? 'dialog open' : 'dialog closed'}</p>
      <ScheduleInterviewDialog
        applicationId="app-1"
        interview={interview}
        open={open}
        onOpenChange={setOpen}
        onDone={onDone}
      />
    </>
  )
}

const setTime = (label: RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
const FUTURE_START = '2031-05-20T09:00'

async function fillValidForm(user: ReturnType<typeof renderWithProviders>['user']) {
  await screen.findByRole('dialog')
  await screen.findByLabelText(/^Starts/)
  await user.selectOptions(screen.getByLabelText(/^Timezone/), 'Europe/Berlin')
  setTime(/^Starts/, FUTURE_START)
  await user.type(screen.getByLabelText(/^Meeting link/), 'https://meet.example.com/abc')
}

describe('ScheduleInterviewDialog', () => {
  it('schedules an interview: explicit timezone, default end, participants, then closes and reports back', async () => {
    signInAs('RECRUITER')
    mockContext()
    let body: Record<string, unknown> | null = null
    server.use(
      http.post(`${API}/interviews`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(makeStaffView({ id: 'iv-new', timezone: 'Europe/Berlin' }), { status: 201 })
      }),
    )
    const onDone = vi.fn()
    const { user } = renderWithProviders(<Harness onDone={onDone} />)
    await fillValidForm(user)
    // the end follows the start by one hour, and the preview names the zone and the UTC equivalent
    expect(screen.getByLabelText(/^Ends/)).toHaveValue('2031-05-20T10:00')
    expect(screen.getByText(/UTC\+02:00/)).toBeInTheDocument()
    expect(screen.getByText(/7:00 AM – 8:00 AM UTC/)).toBeInTheDocument()

    await user.click(screen.getByRole('combobox', { name: /Interviewers/ }))
    await user.click(await screen.findByRole('option', { name: /Ravi Tester/ }))
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('combobox', { name: /Observers/ }))
    await user.click(await screen.findByRole('option', { name: /Hannah Tester/ }))
    await user.keyboard('{Escape}')
    await user.type(screen.getByLabelText(/Internal notes/), 'Focus on system design.')
    await user.click(screen.getByRole('button', { name: 'Schedule interview' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({
      application_id: 'app-1',
      interview_type: 'TECHNICAL',
      start_at: '2031-05-20T09:00:00',
      end_at: '2031-05-20T10:00:00',
      timezone: 'Europe/Berlin',
      location: null,
      meeting_url: 'https://meet.example.com/abc',
      notes: 'Focus on system design.',
    })
    expect(body!.participants).toEqual([
      { user_id: 'user-recruiter', role: 'INTERVIEWER' },
      { user_id: 'user-ravi', role: 'INTERVIEWER' },
      { user_id: 'user-hannah', role: 'OBSERVER' },
    ])
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ id: 'iv-new' })))
    expect(await screen.findByText('dialog closed')).toBeInTheDocument()
  })

  it('offers company staff only: active recruiters and the job\'s own hiring manager', async () => {
    signInAs('RECRUITER')
    mockContext()
    const { user } = renderWithProviders(<Harness />)
    await screen.findByLabelText(/^Starts/)
    await user.click(screen.getByRole('combobox', { name: /Observers/ }))
    const names = (await screen.findAllByRole('option')).map((o) => o.textContent)
    expect(names.some((n) => n?.includes('Ravi Tester'))).toBe(true)
    expect(names.some((n) => n?.includes('Hannah Tester'))).toBe(true)
    expect(names.some((n) => n?.includes('Otto'))).toBe(false)
    expect(names.some((n) => n?.includes('Gone'))).toBe(false)
  })

  it('validates before calling the API', async () => {
    signInAs('RECRUITER')
    mockContext()
    let posted = false
    server.use(
      http.post(`${API}/interviews`, () => {
        posted = true
        return HttpResponse.json(makeStaffView())
      }),
    )
    const { user } = renderWithProviders(<Harness />)
    await screen.findByLabelText(/^Starts/)
    await user.click(screen.getByRole('button', { name: 'Schedule interview' }))
    expect(await screen.findByText('Choose when the interview starts')).toBeInTheDocument()
    expect(screen.getByText('Choose when the interview ends')).toBeInTheDocument()
    expect(screen.getByText('Add a location or a meeting link')).toBeInTheDocument()

    setTime(/^Starts/, FUTURE_START)
    setTime(/^Ends/, '2031-05-20T08:00')
    await user.type(screen.getByLabelText(/^Meeting link/), 'http://not-secure.example.com')
    await user.click(screen.getByRole('button', { name: 'Schedule interview' }))
    expect(await screen.findByText('The interview must end after it starts')).toBeInTheDocument()
    expect(screen.getByText('Use a valid https:// link')).toBeInTheDocument()

    setTime(/^Starts/, '2020-01-01T09:00')
    await user.click(screen.getByRole('button', { name: 'Schedule interview' }))
    expect(await screen.findByText('The interview cannot start in the past')).toBeInTheDocument()
    expect(posted).toBe(false)
  })

  it('shows who is already booked and when on a 409 conflict, stays open, and recovers after adjusting', async () => {
    signInAs('RECRUITER')
    mockContext()
    let attempts = 0
    server.use(
      http.post(`${API}/interviews`, () => {
        attempts += 1
        if (attempts === 1)
          return HttpResponse.json(
            conflictBody('Ravi Patel is already booked from 2031-05-20 07:30 to 08:30 UTC', [
              {
                kind: 'interviewer',
                interview_id: 'iv-x',
                start_at: '2031-05-20T07:30:00+00:00',
                end_at: '2031-05-20T08:30:00+00:00',
                participant: 'Ravi Patel',
              },
              {
                kind: 'candidate',
                interview_id: 'iv-y',
                start_at: '2031-05-20T07:00:00+00:00',
                end_at: '2031-05-20T08:00:00+00:00',
                participant: null,
              },
            ]),
            { status: 409 },
          )
        return HttpResponse.json(makeStaffView({ id: 'iv-ok' }), { status: 201 })
      }),
    )
    const onDone = vi.fn()
    const { user } = renderWithProviders(<Harness onDone={onDone} />)
    await fillValidForm(user)
    await user.click(screen.getByRole('button', { name: 'Schedule interview' }))

    const alert = await screen.findByText('Time conflict: someone is already booked')
    const box = alert.closest('[role="alert"]') as HTMLElement
    expect(within(box).getByText(/Ravi Patel is already booked on .*9:30 AM – 10:30 AM/)).toBeInTheDocument()
    expect(within(box).getByText(/The candidate already has an interview on .*9:00 AM – 10:00 AM/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Starts/)).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('dialog open')).toBeInTheDocument()
    expect(onDone).not.toHaveBeenCalled()

    // adjusting the time removes the stale conflict banner and a retry succeeds
    setTime(/^Starts/, '2031-05-20T14:00')
    await waitFor(() => expect(screen.queryByText('Time conflict: someone is already booked')).not.toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Schedule interview' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ id: 'iv-ok' })))
    expect(attempts).toBe(2)
  })

  it('handles a conflict without details (race) with a plain message', async () => {
    signInAs('RECRUITER')
    mockContext()
    server.use(
      http.post(`${API}/interviews`, () =>
        HttpResponse.json(
          conflictBody('An interviewer was booked by a concurrent request; please choose another time', [
            { kind: 'interviewer', interview_id: null },
          ]),
          { status: 409 },
        ),
      ),
    )
    const { user } = renderWithProviders(<Harness />)
    await fillValidForm(user)
    await user.click(screen.getByRole('button', { name: 'Schedule interview' }))
    expect(await screen.findByText(/An interviewer was booked by another request/)).toBeInTheDocument()
  })

  it('maps server-side field errors onto the form', async () => {
    signInAs('RECRUITER')
    mockContext()
    server.use(
      http.post(`${API}/interviews`, () =>
        HttpResponse.json(
          errorBody('INVALID_PARTICIPANT', 'Participants must be active recruiters or hiring managers of your company'),
          { status: 422 },
        ),
      ),
    )
    const { user } = renderWithProviders(<Harness />)
    await fillValidForm(user)
    await user.click(screen.getByRole('button', { name: 'Schedule interview' }))
    expect(await screen.findByText(/Participants must be active recruiters/)).toBeInTheDocument()
    expect(screen.getByText('dialog open')).toBeInTheDocument()
  })

  it('refuses to schedule applications that are not shortlisted', async () => {
    signInAs('RECRUITER')
    mockContext('APPLIED')
    renderWithProviders(<Harness />)
    expect(await screen.findByText('This application cannot be scheduled yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Schedule interview' })).toBeDisabled()
  })

  it('shows loading, then an error with retry when the application cannot be loaded', async () => {
    signInAs('RECRUITER')
    let fail = true
    server.use(
      http.get(`${API}/applications/app-1`, () =>
        fail ? HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 }) : HttpResponse.json(application()),
      ),
      http.get(`${API}/jobs/job-1`, () => HttpResponse.json({ id: 'job-1', hiring_manager_id: null })),
      http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([makeMember('user-recruiter', 'Riley')])),
    )
    const { user } = renderWithProviders(<Harness />)
    expect(await screen.findByRole('status', { name: /Loading scheduling details/ })).toBeInTheDocument()
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByLabelText(/^Starts/)).toBeInTheDocument()
  })

  describe('rescheduling', () => {
    const existing = makeStaffView({
      id: 'iv-1',
      start_at: '2031-05-20T08:00:00Z',
      end_at: '2031-05-20T09:00:00Z',
      timezone: 'Europe/Berlin',
      notes: 'Keep these notes',
      status: 'CONFIRMED',
      participants: [
        { user_id: 'user-ravi', name: 'Ravi Tester', role: 'INTERVIEWER', has_submitted_feedback: false },
        { user_id: 'user-hannah', name: 'Hannah Tester', role: 'OBSERVER', has_submitted_feedback: false },
      ],
    })

    it('prefills from the interview (in its own timezone) and sends a PATCH with the new time', async () => {
      signInAs('RECRUITER')
      mockContext()
      let body: Record<string, unknown> | null = null
      server.use(
        http.patch(`${API}/interviews/iv-1`, async ({ request }) => {
          body = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({ ...existing, status: 'RESCHEDULED' })
        }),
      )
      const onDone = vi.fn()
      const { user } = renderWithProviders(<Harness interview={existing} onDone={onDone} />)
      const start = await screen.findByLabelText(/^Starts/)
      expect(start).toHaveValue('2031-05-20T10:00')
      expect(screen.getByLabelText(/^Timezone/)).toHaveValue('Europe/Berlin')
      expect(screen.getByRole('button', { name: 'Save changes' })).toBeInTheDocument()

      setTime(/^Starts/, '2031-05-21T15:00')
      expect(screen.getByLabelText(/^Ends/)).toHaveValue('2031-05-21T16:00')
      await user.click(screen.getByRole('button', { name: 'Reschedule interview' }))
      await waitFor(() => expect(body).not.toBeNull())
      expect(body).toMatchObject({
        start_at: '2031-05-21T15:00:00',
        end_at: '2031-05-21T16:00:00',
        timezone: 'Europe/Berlin',
        notes: 'Keep these notes',
        participants: [
          { user_id: 'user-ravi', role: 'INTERVIEWER' },
          { user_id: 'user-hannah', role: 'OBSERVER' },
        ],
      })
      expect(body).not.toHaveProperty('application_id')
      await waitFor(() => expect(onDone).toHaveBeenCalled())
    })

    it('loads the full record (with internal notes) when given a list item, so saving never wipes them', async () => {
      signInAs('RECRUITER')
      mockContext()
      server.use(http.get(`${API}/interviews/iv-1`, () => HttpResponse.json(existing)))
      const { notes: _notes, ...item } = existing
      void _notes
      renderWithProviders(<Harness interview={item as unknown as StaffInterviewItem} />)
      expect(await screen.findByLabelText(/Internal notes/)).toHaveValue('Keep these notes')
    })
  })
})
