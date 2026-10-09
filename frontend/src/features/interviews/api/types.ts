/**
 * Interview API shapes. `/interviews` is live in the backend but was not part of the generated
 * `lib/api/schema.d.ts` snapshot when this module was written, so the minimal shapes are declared here
 * (mirroring `backend/app/schemas/interview.py`). Once `npm run gen:api` is re-run these can be aliased instead.
 */
import type { ApplicationStatus } from '@/lib/api'

export const INTERVIEW_STATUSES = [
  'SCHEDULED',
  'CONFIRMED',
  'RESCHEDULED',
  'COMPLETED',
  'CANCELLED',
  'NO_SHOW',
] as const
export type InterviewStatus = (typeof INTERVIEW_STATUSES)[number]

export const INTERVIEW_TYPES = ['PHONE_SCREEN', 'TECHNICAL', 'BEHAVIORAL', 'PANEL', 'ONSITE', 'FINAL'] as const
export type InterviewType = (typeof INTERVIEW_TYPES)[number]

export type ParticipantRole = 'INTERVIEWER' | 'OBSERVER'

export const RECOMMENDATIONS = ['STRONG_HIRE', 'HIRE', 'NO_HIRE', 'STRONG_NO_HIRE'] as const
export type HireRecommendation = (typeof RECOMMENDATIONS)[number]

export interface ParticipantOut {
  user_id: string
  name: string
  role: ParticipantRole
  has_submitted_feedback: boolean
}

export interface StaffInterviewItem {
  audience: 'staff'
  id: string
  application_id: string
  job_id: string
  job_title: string
  candidate_id: string
  candidate_name: string
  interview_type: InterviewType
  start_at: string
  end_at: string
  timezone: string
  location: string | null
  meeting_url: string | null
  status: InterviewStatus
  participants: ParticipantOut[]
  feedback_count: number
}

export interface StaffInterviewView extends StaffInterviewItem {
  company_id: string
  company_name: string
  start_local: string
  end_local: string
  duration_minutes: number
  notes: string | null
  cancelled_reason: string | null
  created_by_id: string | null
  created_by_name: string | null
  my_feedback_submitted: boolean
  can_submit_feedback: boolean
  application: {
    id: string
    status: ApplicationStatus
    allowed_next_statuses: ApplicationStatus[]
  }
  created_at: string
  updated_at: string
}

/** Logistics only: the backend never puts notes, feedback, ratings or staff contact data in this shape. */
export interface CandidateInterviewView {
  audience: 'candidate'
  id: string
  application_id: string
  job_id: string
  job_title: string
  company_name: string
  interview_type: InterviewType
  start_at: string
  end_at: string
  start_local: string
  end_local: string
  timezone: string
  duration_minutes: number
  location: string | null
  meeting_url: string | null
  status: InterviewStatus
  interviewers: string[]
  can_confirm: boolean
}

export type InterviewListEntry = StaffInterviewItem | CandidateInterviewView
export type InterviewDetail = StaffInterviewView | CandidateInterviewView

export const isStaffInterview = <T extends InterviewListEntry>(i: T): i is Extract<T, { audience: 'staff' }> =>
  i.audience === 'staff'

export interface ParticipantIn {
  user_id: string
  role: ParticipantRole
}

export interface InterviewCreate {
  application_id: string
  interview_type: InterviewType
  /** Naive local date-time (`2030-05-20T09:00:00`) is read in `timezone` by the backend. */
  start_at: string
  end_at: string
  timezone: string
  location: string | null
  meeting_url: string | null
  notes: string | null
  participants: ParticipantIn[]
}

export type InterviewUpdate = Partial<Omit<InterviewCreate, 'application_id'>>

export interface FeedbackIn {
  rating: number
  recommendation: HireRecommendation
  strengths: string | null
  weaknesses: string | null
  notes: string | null
}

export interface FeedbackOut extends FeedbackIn {
  id: string
  interview_id: string
  author_id: string
  author_name: string
  submitted_at: string
  is_mine: boolean
}

export interface FeedbackSummary {
  interview_id: string
  count: number
  average_rating: number | null
  recommendations: Partial<Record<HireRecommendation, number>>
  items: FeedbackOut[]
}

/** One entry of `details.conflicts` in a 409 INTERVIEW_CONFLICT response. */
export interface InterviewConflict {
  kind: 'candidate' | 'interviewer'
  interview_id: string | null
  start_at: string | null
  end_at: string | null
  participant: string | null
}
