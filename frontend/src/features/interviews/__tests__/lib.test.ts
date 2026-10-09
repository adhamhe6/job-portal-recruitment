import { describe, expect, it } from 'vitest'
import { ApiError } from '@/lib/api'
import { describeConflict, parseConflicts } from '../lib/conflicts'
import { groupByDay } from '../lib/agenda'
import { makeScheduleSchema, toCreatePayload, toUpdatePayload, type ScheduleFormValues } from '../lib/schedule'
import { feedbackBlockedReason, interviewActions } from '../lib/stateMachine'
import {
  addMinutesToLocal,
  formatSlot,
  instantToLocalInput,
  isValidTimeZone,
  offsetLabel,
  wallTimeToInstant,
} from '../lib/time'
import { makeStaffInterview } from './fixtures'

describe('timezone helpers', () => {
  it('reads wall-clock time in an explicit zone (summer and winter offsets)', () => {
    expect(wallTimeToInstant('2030-07-01T10:00', 'Europe/Berlin')?.toISOString()).toBe('2030-07-01T08:00:00.000Z')
    expect(wallTimeToInstant('2030-01-15T10:00', 'Europe/Berlin')?.toISOString()).toBe('2030-01-15T09:00:00.000Z')
    expect(wallTimeToInstant('2030-07-01T10:00', 'America/New_York')?.toISOString()).toBe('2030-07-01T14:00:00.000Z')
    expect(wallTimeToInstant('2030-07-01T10:00', 'UTC')?.toISOString()).toBe('2030-07-01T10:00:00.000Z')
    expect(wallTimeToInstant('nonsense', 'UTC')).toBeNull()
  })

  it('round-trips an instant to the zone wall clock', () => {
    expect(instantToLocalInput('2030-07-01T08:00:00Z', 'Europe/Berlin')).toBe('2030-07-01T10:00')
    expect(instantToLocalInput('2030-07-01T23:30:00Z', 'Asia/Tokyo')).toBe('2030-07-02T08:30')
  })

  it('names the zone in every rendered slot', () => {
    const text = formatSlot('2030-07-01T08:00:00Z', '2030-07-01T09:00:00Z', 'Europe/Berlin')
    expect(text).toContain('10:00 AM')
    expect(text).toMatch(/GMT\+2|CEST/)
    expect(offsetLabel(new Date('2030-07-01T08:00:00Z'), 'Europe/Berlin')).toBe('UTC+02:00')
    expect(offsetLabel(new Date('2030-07-01T08:00:00Z'), 'Asia/Kolkata')).toBe('UTC+05:30')
    expect(offsetLabel(new Date('2030-07-01T08:00:00Z'), 'UTC')).toBe('UTC')
  })

  it('validates IANA names and does simple wall-clock arithmetic', () => {
    expect(isValidTimeZone('Europe/Berlin')).toBe(true)
    expect(isValidTimeZone('Mars/Olympus')).toBe(false)
    expect(addMinutesToLocal('2030-07-01T23:30', 60)).toBe('2030-07-02T00:30')
  })
})

describe('schedule form schema', () => {
  const valid: ScheduleFormValues = {
    interview_type: 'TECHNICAL',
    timezone: 'Europe/Berlin',
    start: '2030-05-20T09:00',
    end: '2030-05-20T10:00',
    location: '',
    meeting_url: 'https://meet.example.com/abc',
    notes: '',
    interviewers: ['u1'],
    observers: [],
  }
  const now = () => new Date('2030-05-01T00:00:00Z')
  const issues = (v: Partial<ScheduleFormValues>, opts = {}) => {
    const r = makeScheduleSchema({ now, ...opts }).safeParse({ ...valid, ...v })
    return r.success ? {} : Object.fromEntries(r.error.issues.map((i) => [String(i.path[0]), i.message]))
  }

  it('accepts a valid slot', () => expect(issues({})).toEqual({}))
  it('needs an interviewer, a location or link, and an https link', () => {
    expect(issues({ interviewers: [] }).interviewers).toMatch(/at least one interviewer/i)
    expect(issues({ meeting_url: '', location: '' }).location).toMatch(/location or a meeting link/i)
    expect(issues({ meeting_url: 'http://insecure.example.com' }).meeting_url).toMatch(/https/)
    expect(issues({ meeting_url: '', location: 'HQ' })).toEqual({})
  })
  it('rejects bad time ranges', () => {
    expect(issues({ end: '2030-05-20T09:00' }).end).toMatch(/end after it starts/)
    expect(issues({ end: '2030-05-20T22:00' }).end).toMatch(/12 hours/)
    expect(issues({ start: '2030-04-30T09:00', end: '2030-04-30T10:00' }).start).toMatch(/past/)
  })
  it('does not reject an unchanged past slot when only details are edited', () => {
    const original = { start: '2030-04-30T09:00', end: '2030-04-30T10:00', timezone: 'Europe/Berlin' }
    const past = { start: original.start, end: original.end, notes: 'new note' }
    expect(issues(past, { original })).toEqual({})
    expect(issues({ ...past, start: '2030-04-30T08:00' }, { original }).start).toMatch(/past/)
  })
  it('keeps interviewers and observers disjoint', () => {
    expect(issues({ observers: ['u1'] }).observers).toMatch(/both/)
  })

  it('builds API payloads with naive local times and explicit timezone', () => {
    const create = toCreatePayload('app-1', { ...valid, notes: '  hi  ', observers: ['u2'] })
    expect(create).toMatchObject({
      application_id: 'app-1',
      start_at: '2030-05-20T09:00:00',
      end_at: '2030-05-20T10:00:00',
      timezone: 'Europe/Berlin',
      location: null,
      meeting_url: 'https://meet.example.com/abc',
      participants: [
        { user_id: 'u1', role: 'INTERVIEWER' },
        { user_id: 'u2', role: 'OBSERVER' },
      ],
    })
    expect(toUpdatePayload(valid)).not.toHaveProperty('application_id')
  })
})

describe('state machine', () => {
  const past = new Date(Date.now() - 3_600_000).toISOString()
  const future = new Date(Date.now() + 3_600_000).toISOString()
  it('lets recruiters reschedule/cancel active interviews and finish them only after the start', () => {
    const a = interviewActions({ status: 'SCHEDULED', startAt: future, canManage: true, isParticipant: false })
    expect(a.reschedule.allowed && a.cancel.allowed).toBe(true)
    expect(a.complete.allowed).toBe(false)
    expect(a.complete.reason).toMatch(/started/)
    const b = interviewActions({ status: 'CONFIRMED', startAt: past, canManage: true, isParticipant: false })
    expect(b.complete.allowed && b.noShow.allowed).toBe(true)
  })
  it('gives a participating hiring manager only the finishing actions', () => {
    const a = interviewActions({ status: 'RESCHEDULED', startAt: past, canManage: false, isParticipant: true })
    expect(a).toMatchObject({
      reschedule: { allowed: false },
      cancel: { allowed: false },
      complete: { allowed: true },
      noShow: { allowed: true },
    })
    expect(interviewActions({ status: 'SCHEDULED', startAt: past, canManage: false, isParticipant: false }).any).toBe(false)
  })
  it('offers nothing for terminal states', () => {
    for (const status of ['COMPLETED', 'CANCELLED', 'NO_SHOW'] as const)
      expect(interviewActions({ status, startAt: past, canManage: true, isParticipant: true }).any).toBe(false)
  })
  it('explains why feedback is blocked', () => {
    expect(feedbackBlockedReason('SCHEDULED', future)).toMatch(/opens once/)
    expect(feedbackBlockedReason('CANCELLED', past)).toMatch(/cancelled/)
    expect(feedbackBlockedReason('NO_SHOW', past)).toMatch(/no-show/)
    expect(feedbackBlockedReason('COMPLETED', past)).toBeNull()
  })
})

describe('conflicts', () => {
  const err = (code: string, details: unknown) => new ApiError(409, code, 'x', details)
  it('parses the structured 409 details and ignores other errors', () => {
    const list = parseConflicts(
      err('INTERVIEW_CONFLICT', {
        conflicts: [
          { kind: 'interviewer', interview_id: 'i1', start_at: '2030-05-20T08:00:00+00:00', end_at: '2030-05-20T09:00:00+00:00', participant: 'Ravi Patel' },
          { kind: 'candidate', interview_id: null },
        ],
      }),
    )
    expect(list).toHaveLength(2)
    expect(list?.[0]).toMatchObject({ kind: 'interviewer', participant: 'Ravi Patel' })
    expect(parseConflicts(err('INVALID_STATE_TRANSITION', null))).toBeNull()
    expect(parseConflicts(new Error('boom'))).toBeNull()
  })
  it('describes who is booked and when, in the form timezone', () => {
    const text = describeConflict(
      { kind: 'interviewer', interview_id: 'i1', start_at: '2030-05-20T08:00:00Z', end_at: '2030-05-20T09:00:00Z', participant: 'Ravi Patel' },
      'Europe/Berlin',
    )
    expect(text).toContain('Ravi Patel is already booked')
    expect(text).toContain('10:00 AM')
    expect(
      describeConflict({ kind: 'candidate', interview_id: 'i1', start_at: '2030-05-20T08:00:00Z', end_at: '2030-05-20T09:00:00Z', participant: null }, 'UTC'),
    ).toContain('The candidate already has an interview')
    expect(describeConflict({ kind: 'candidate', interview_id: null, start_at: null, end_at: null, participant: null }, 'UTC')).toMatch(/booked by another request/)
  })
})

describe('agenda grouping', () => {
  it('groups by viewer-local day, in API order, labelling today and tomorrow', () => {
    const now = new Date('2030-05-20T12:00:00Z')
    const a = makeStaffInterview({ id: 'a', start_at: '2030-05-20T09:00:00Z' })
    const b = makeStaffInterview({ id: 'b', start_at: '2030-05-20T15:00:00Z' })
    const c = makeStaffInterview({ id: 'c', start_at: '2030-05-21T08:00:00Z' })
    const d = makeStaffInterview({ id: 'd', start_at: '2030-05-25T08:00:00Z' })
    const days = groupByDay([a, b, c, d], 'UTC', now)
    expect(days.map((x) => x.items.map((i) => i.id))).toEqual([['a', 'b'], ['c'], ['d']])
    expect(days[0]!.heading).toMatch(/^Today · /)
    expect(days[1]!.heading).toMatch(/^Tomorrow · /)
    expect(days[2]!.heading).not.toMatch(/Today|Tomorrow/)
  })
  it('uses the viewer timezone for the day boundary', () => {
    const now = new Date('2030-05-20T12:00:00Z')
    const late = makeStaffInterview({ id: 'late', start_at: '2030-05-20T23:30:00Z' })
    expect(groupByDay([late], 'UTC', now)[0]!.key).toBe('2030-05-20')
    expect(groupByDay([late], 'Asia/Tokyo', now)[0]!.key).toBe('2030-05-21')
  })
})
