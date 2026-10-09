import type { ApplicationStatus } from '@/lib/api'

/** Main-line stages, in order, followed by the two terminal branches. */
export const PIPELINE_STAGES: ApplicationStatus[] = [
  'APPLIED',
  'SCREENING',
  'SHORTLISTED',
  'INTERVIEW',
  'OFFER',
  'HIRED',
]
export const BRANCH_STAGES: ApplicationStatus[] = ['REJECTED', 'WITHDRAWN']
export const ALL_STAGES: ApplicationStatus[] = [...PIPELINE_STAGES, ...BRANCH_STAGES]

/** Mirrors backend services/applications.py::TRANSITIONS minus WITHDRAWN (candidate-only). The server stays the authority. */
const STAFF_TRANSITIONS: Record<ApplicationStatus, ApplicationStatus[]> = {
  APPLIED: ['SCREENING', 'REJECTED'],
  SCREENING: ['SHORTLISTED', 'REJECTED'],
  SHORTLISTED: ['INTERVIEW', 'REJECTED'],
  INTERVIEW: ['OFFER', 'REJECTED'],
  OFFER: ['HIRED', 'REJECTED'],
  HIRED: [],
  REJECTED: [],
  WITHDRAWN: [],
}

/** Targets a recruiter may move an application to; `fromApi` (detail.allowed_next_statuses) wins when present. */
export function staffTargets(status: ApplicationStatus, fromApi?: ApplicationStatus[]): ApplicationStatus[] {
  const targets = fromApi ?? STAFF_TRANSITIONS[status]
  return ALL_STAGES.filter((s) => targets.includes(s) && s !== 'WITHDRAWN')
}

export const isTerminal = (s: ApplicationStatus) => s === 'HIRED' || s === 'REJECTED' || s === 'WITHDRAWN'

/** Candidates can withdraw only before shortlisting (backend CANNOT_WITHDRAW). */
export const canWithdraw = (s: ApplicationStatus) => s === 'APPLIED' || s === 'SCREENING'

/** Rejection should carry a reason; every other move may carry an optional comment. */
export const asksForReason = (target: ApplicationStatus) => target === 'REJECTED'

/** Interviews can only be scheduled for these stages (backend APPLICATION_NOT_INTERVIEWABLE). */
export const canScheduleInterview = (s: ApplicationStatus) => s === 'SHORTLISTED' || s === 'INTERVIEW'

/** Verb phrase for a move, used on menu items and buttons. */
export function moveLabel(target: ApplicationStatus): string {
  switch (target) {
    case 'SCREENING':
      return 'Start screening'
    case 'SHORTLISTED':
      return 'Shortlist'
    case 'INTERVIEW':
      return 'Move to interview'
    case 'OFFER':
      return 'Make offer'
    case 'HIRED':
      return 'Mark as hired'
    case 'REJECTED':
      return 'Reject'
    default:
      return target
  }
}
