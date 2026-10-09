import type { InterviewStatus } from '../api/types'

/**
 * Interview state machine (mirrors backend/app/services/interviews.py):
 *
 *   SCHEDULED ──candidate confirms──▶ CONFIRMED
 *   SCHEDULED | CONFIRMED | RESCHEDULED  ──edit time──▶ RESCHEDULED   (candidate must confirm again)
 *   SCHEDULED | CONFIRMED | RESCHEDULED  ──cancel──▶ CANCELLED          (recruiters, admins)
 *   SCHEDULED | CONFIRMED | RESCHEDULED  ──after the start time──▶ COMPLETED | NO_SHOW
 *
 * COMPLETED, CANCELLED and NO_SHOW are terminal.
 */
export const ACTIVE_STATUSES: readonly InterviewStatus[] = ['SCHEDULED', 'CONFIRMED', 'RESCHEDULED']
export const isActiveStatus = (s: InterviewStatus) => ACTIVE_STATUSES.includes(s)

export interface ActionAvailability {
  allowed: boolean
  /** Why an action that looks relevant is unavailable right now (shown as a hint). */
  reason?: string
}

export interface InterviewActions {
  reschedule: ActionAvailability
  cancel: ActionAvailability
  complete: ActionAvailability
  noShow: ActionAvailability
  /** True when at least one action is usable. */
  any: boolean
}

const NO: ActionAvailability = { allowed: false }

/**
 * What the current user may do with an interview.
 * - `canManage`: recruiter of the company or admin (reschedule / cancel / finish)
 * - `isParticipant`: a hiring manager taking part may only mark the interview completed / no-show
 */
export function interviewActions({
  status,
  startAt,
  canManage,
  isParticipant,
  now = new Date(),
}: {
  status: InterviewStatus
  startAt: string
  canManage: boolean
  isParticipant: boolean
  now?: Date
}): InterviewActions {
  if (!isActiveStatus(status)) return { reschedule: NO, cancel: NO, complete: NO, noShow: NO, any: false }
  const started = new Date(startAt).getTime() <= now.getTime()
  const mayFinish = canManage || isParticipant
  const finish: ActionAvailability = !mayFinish
    ? NO
    : started
      ? { allowed: true }
      : { allowed: false, reason: 'Available once the interview has started.' }
  const result = {
    reschedule: canManage ? { allowed: true } : NO,
    cancel: canManage ? { allowed: true } : NO,
    complete: finish,
    noShow: finish,
  }
  return { ...result, any: Object.values(result).some((a) => a.allowed) }
}

/** Plain-language explanation of why feedback cannot be submitted right now. */
export function feedbackBlockedReason(status: InterviewStatus, startAt: string, now = new Date()): string | null {
  if (status === 'CANCELLED' || status === 'NO_SHOW')
    return `Feedback cannot be recorded for a ${status === 'NO_SHOW' ? 'no-show' : 'cancelled'} interview.`
  if (status !== 'COMPLETED' && new Date(startAt).getTime() > now.getTime())
    return 'Feedback opens once the interview has started.'
  return null
}
