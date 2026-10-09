import type { Option } from '@/lib/enums'
import {
  INTERVIEW_STATUSES,
  INTERVIEW_TYPES,
  RECOMMENDATIONS,
  type HireRecommendation,
  type InterviewStatus,
  type InterviewType,
} from '../api/types'

export const INTERVIEW_TYPE_LABELS: Record<InterviewType, string> = {
  PHONE_SCREEN: 'Phone screen',
  TECHNICAL: 'Technical interview',
  BEHAVIORAL: 'Behavioral interview',
  PANEL: 'Panel interview',
  ONSITE: 'On-site interview',
  FINAL: 'Final interview',
}

export const INTERVIEW_STATUS_LABELS: Record<InterviewStatus, string> = {
  SCHEDULED: 'Scheduled',
  CONFIRMED: 'Confirmed',
  RESCHEDULED: 'Rescheduled',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
  NO_SHOW: 'No-show',
}

export const RECOMMENDATION_LABELS: Record<HireRecommendation, string> = {
  STRONG_HIRE: 'Strong hire',
  HIRE: 'Hire',
  NO_HIRE: 'No hire',
  STRONG_NO_HIRE: 'Strong no hire',
}

export const RATING_LABELS: Record<number, string> = {
  1: 'Poor',
  2: 'Below expectations',
  3: 'Meets expectations',
  4: 'Strong',
  5: 'Outstanding',
}

export const INTERVIEW_TYPE_OPTIONS: Option<InterviewType>[] = INTERVIEW_TYPES.map((value) => ({
  value,
  label: INTERVIEW_TYPE_LABELS[value],
}))
export const INTERVIEW_STATUS_OPTIONS: Option<InterviewStatus>[] = INTERVIEW_STATUSES.map((value) => ({
  value,
  label: INTERVIEW_STATUS_LABELS[value],
}))
export const RECOMMENDATION_OPTIONS: Option<HireRecommendation>[] = RECOMMENDATIONS.map((value) => ({
  value,
  label: RECOMMENDATION_LABELS[value],
}))

/** Short, human title for an interview: "Technical interview". */
export const interviewTypeLabel = (t: string) =>
  INTERVIEW_TYPE_LABELS[t as InterviewType] ?? t.replace(/_/g, ' ').toLowerCase()
