import { z } from 'zod'
import { INTERVIEW_TYPES, type InterviewCreate, type InterviewUpdate, type ParticipantIn } from '../api/types'
import { addMinutesToLocal, isValidTimeZone, minutesBetweenLocal, wallTimeToInstant } from './time'

/** Backend limits (backend/app/services/interviews.py + schemas/interview.py). */
export const MAX_DURATION_MINUTES = 12 * 60
export const PAST_TOLERANCE_MINUTES = 5
export const MAX_PARTICIPANTS = 15
export const DEFAULT_DURATION_MINUTES = 60

export interface ScheduleFormValues {
  interview_type: (typeof INTERVIEW_TYPES)[number]
  timezone: string
  /** `yyyy-MM-ddTHH:mm` wall time in `timezone` */
  start: string
  end: string
  location: string
  meeting_url: string
  notes: string
  interviewers: string[]
  observers: string[]
}

export interface ScheduleSchemaOptions {
  /** Reschedule: the original slot; the "not in the past" rule only applies when the time actually changes. */
  original?: { start: string; end: string; timezone: string }
  now?: () => Date
}

export function makeScheduleSchema({ original, now = () => new Date() }: ScheduleSchemaOptions = {}) {
  return z
    .object({
      interview_type: z.enum(INTERVIEW_TYPES),
      timezone: z.string().refine(isValidTimeZone, 'Choose a valid timezone'),
      start: z.string().min(1, 'Choose when the interview starts'),
      end: z.string().min(1, 'Choose when the interview ends'),
      location: z.string().trim().max(300, 'Keep the location under 300 characters'),
      meeting_url: z.string().trim().max(500, 'Keep the link under 500 characters'),
      notes: z.string().max(4000, 'Keep the notes under 4,000 characters'),
      interviewers: z.array(z.string()).min(1, 'Choose at least one interviewer'),
      observers: z.array(z.string()),
    })
    .superRefine((v, ctx) => {
      const add = (path: keyof ScheduleFormValues, message: string) =>
        ctx.addIssue({ code: 'custom', path: [path], message })

      if (v.meeting_url && !isHttps(v.meeting_url)) add('meeting_url', 'Use a valid https:// link')
      if (!v.location && !v.meeting_url) {
        add('location', 'Add a location or a meeting link')
        add('meeting_url', 'Add a meeting link or a location')
      }
      const overlap = v.interviewers.filter((id) => v.observers.includes(id))
      if (overlap.length) add('observers', 'Someone cannot be both an interviewer and an observer')
      if (new Set([...v.interviewers, ...v.observers]).size > MAX_PARTICIPANTS)
        add('interviewers', `At most ${MAX_PARTICIPANTS} participants`)

      if (!v.start || !v.end || !isValidTimeZone(v.timezone)) return
      const start = wallTimeToInstant(v.start, v.timezone)
      const end = wallTimeToInstant(v.end, v.timezone)
      if (!start) return add('start', 'Enter a valid start time')
      if (!end) return add('end', 'Enter a valid end time')
      if (end <= start) return add('end', 'The interview must end after it starts')
      if ((end.getTime() - start.getTime()) / 60_000 > MAX_DURATION_MINUTES)
        return add('end', 'An interview cannot last longer than 12 hours')

      const timeChanged =
        !original || original.start !== v.start || original.end !== v.end || original.timezone !== v.timezone
      if (timeChanged && start.getTime() < now().getTime() - PAST_TOLERANCE_MINUTES * 60_000)
        add('start', 'The interview cannot start in the past')
    })
}

function isHttps(value: string): boolean {
  try {
    const u = new URL(value)
    return u.protocol === 'https:' && !/\s/.test(value)
  } catch {
    return false
  }
}

const nullable = (s: string) => s.trim() || null

export function toParticipants(v: Pick<ScheduleFormValues, 'interviewers' | 'observers'>): ParticipantIn[] {
  return [
    ...v.interviewers.map((user_id) => ({ user_id, role: 'INTERVIEWER' as const })),
    ...v.observers.map((user_id) => ({ user_id, role: 'OBSERVER' as const })),
  ]
}

const asApiDateTime = (local: string) => (local.length === 16 ? `${local}:00` : local)

export function toCreatePayload(applicationId: string, v: ScheduleFormValues): InterviewCreate {
  return {
    application_id: applicationId,
    interview_type: v.interview_type,
    start_at: asApiDateTime(v.start),
    end_at: asApiDateTime(v.end),
    timezone: v.timezone,
    location: nullable(v.location),
    meeting_url: nullable(v.meeting_url),
    notes: nullable(v.notes),
    participants: toParticipants(v),
  }
}

export function toUpdatePayload(v: ScheduleFormValues): InterviewUpdate {
  const { application_id: _drop, ...rest } = toCreatePayload('', v)
  void _drop
  return rest
}

/** Default end when the start changes: keep the current duration (or 60 minutes). */
export function endAfterStartChange(prevStart: string, prevEnd: string, nextStart: string): string {
  const prev = prevStart && prevEnd ? minutesBetweenLocal(prevStart, prevEnd) : null
  const minutes = prev && prev > 0 && prev <= MAX_DURATION_MINUTES ? prev : DEFAULT_DURATION_MINUTES
  return addMinutesToLocal(nextStart, minutes)
}
