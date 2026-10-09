import { ApiError } from '@/lib/api'
import type { InterviewConflict } from '../api/types'
import { formatSlot, isValidTimeZone } from './time'

/** The structured clashes of a 409 `INTERVIEW_CONFLICT`, or null when `error` is anything else. */
export function parseConflicts(error: unknown): InterviewConflict[] | null {
  if (!(error instanceof ApiError) || !error.is('INTERVIEW_CONFLICT')) return null
  const raw = (error.details as { conflicts?: unknown } | null)?.conflicts
  const list = Array.isArray(raw) ? raw : []
  const out: InterviewConflict[] = []
  for (const c of list) {
    if (!c || typeof c !== 'object') continue
    const r = c as Record<string, unknown>
    out.push({
      kind: r.kind === 'candidate' ? 'candidate' : 'interviewer',
      interview_id: typeof r.interview_id === 'string' ? r.interview_id : null,
      start_at: typeof r.start_at === 'string' ? r.start_at : null,
      end_at: typeof r.end_at === 'string' ? r.end_at : null,
      participant: typeof r.participant === 'string' ? r.participant : null,
    })
  }
  return out
}

/** "Dana Lee is already booked Thu, Oct 9, 2026 · 2:00 PM – 3:00 PM CEST" (time shown in the form's timezone). */
export function describeConflict(c: InterviewConflict, tz: string): string {
  const zone = isValidTimeZone(tz) ? tz : 'UTC'
  const who = c.kind === 'candidate' ? 'The candidate' : (c.participant ?? 'An interviewer')
  if (!c.start_at || !c.end_at) {
    return c.kind === 'candidate'
      ? 'The candidate was booked by another request at the same moment.'
      : 'An interviewer was booked by another request at the same moment.'
  }
  const verb = c.kind === 'candidate' ? 'already has an interview' : 'is already booked'
  return `${who} ${verb} on ${formatSlot(c.start_at, c.end_at, zone)}`
}
