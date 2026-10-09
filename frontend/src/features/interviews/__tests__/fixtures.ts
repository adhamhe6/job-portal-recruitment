import { COMPANY_ID, uid } from '@/test/fixtures'
import type {
  CandidateInterviewView,
  FeedbackOut,
  FeedbackSummary,
  StaffInterviewItem,
  StaffInterviewView,
} from '../api/types'

const HOUR = 3_600_000
export const inHours = (h: number) => new Date(Date.now() + h * HOUR).toISOString()

export const RILEY = { user_id: 'user-recruiter', name: 'Riley Recruiter' }
export const RAVI = { user_id: 'user-ravi', name: 'Ravi Patel' }
export const HANNAH = { user_id: 'user-hannah', name: 'Hannah Manager' }

export function makeStaffInterview(overrides: Partial<StaffInterviewItem> = {}): StaffInterviewItem {
  const start = overrides.start_at ?? inHours(26)
  return {
    audience: 'staff',
    id: uid('iv'),
    application_id: 'app-1',
    job_id: 'job-1',
    job_title: 'Senior Backend Engineer',
    candidate_id: 'cand-9',
    candidate_name: 'Nina Petrova',
    interview_type: 'TECHNICAL',
    start_at: start,
    end_at: new Date(new Date(start).getTime() + HOUR).toISOString(),
    timezone: 'UTC',
    location: null,
    meeting_url: 'https://meet.example.com/abc',
    status: 'SCHEDULED',
    participants: [
      { ...RAVI, role: 'INTERVIEWER', has_submitted_feedback: false },
      { ...HANNAH, role: 'OBSERVER', has_submitted_feedback: false },
    ],
    feedback_count: 0,
    ...overrides,
  }
}

export function makeStaffView(overrides: Partial<StaffInterviewView> = {}): StaffInterviewView {
  const base = makeStaffInterview(overrides)
  return {
    ...base,
    company_id: COMPANY_ID,
    company_name: 'Northwind Labs',
    start_local: base.start_at.replace('Z', '+00:00'),
    end_local: base.end_at.replace('Z', '+00:00'),
    duration_minutes: 60,
    notes: 'Focus on system design.',
    cancelled_reason: null,
    created_by_id: RILEY.user_id,
    created_by_name: RILEY.name,
    my_feedback_submitted: false,
    can_submit_feedback: false,
    application: { id: base.application_id, status: 'INTERVIEW', allowed_next_statuses: ['OFFER', 'REJECTED'] },
    created_at: '2026-10-01T09:00:00Z',
    updated_at: '2026-10-01T09:00:00Z',
    ...overrides,
  }
}

export function makeCandidateView(overrides: Partial<CandidateInterviewView> = {}): CandidateInterviewView {
  const start = overrides.start_at ?? inHours(48)
  return {
    audience: 'candidate',
    id: 'iv-cand-1',
    application_id: 'app-1',
    job_id: 'job-1',
    job_title: 'Senior Backend Engineer',
    company_name: 'Northwind Labs',
    interview_type: 'TECHNICAL',
    start_at: start,
    end_at: new Date(new Date(start).getTime() + HOUR).toISOString(),
    start_local: start,
    end_local: start,
    timezone: 'UTC',
    duration_minutes: 60,
    location: null,
    meeting_url: 'https://meet.example.com/abc',
    status: 'SCHEDULED',
    interviewers: ['Ravi Patel'],
    can_confirm: true,
    ...overrides,
  }
}

export function makeFeedback(overrides: Partial<FeedbackOut> = {}): FeedbackOut {
  return {
    id: uid('fb'),
    interview_id: 'iv-1',
    author_id: RAVI.user_id,
    author_name: RAVI.name,
    rating: 4,
    recommendation: 'HIRE',
    strengths: 'Clear communicator.',
    weaknesses: null,
    notes: null,
    submitted_at: '2026-10-08T10:00:00Z',
    is_mine: false,
    ...overrides,
  }
}

export function makeFeedbackSummary(items: FeedbackOut[] = []): FeedbackSummary {
  const rec: FeedbackSummary['recommendations'] = {}
  for (const i of items) rec[i.recommendation] = (rec[i.recommendation] ?? 0) + 1
  return {
    interview_id: 'iv-1',
    count: items.length,
    average_rating: items.length ? items.reduce((s, i) => s + i.rating, 0) / items.length : null,
    recommendations: rec,
    items,
  }
}

export const makeMember = (id: string, first: string, role: 'RECRUITER' | 'HIRING_MANAGER' = 'RECRUITER') => ({
  id,
  email: `${first.toLowerCase()}@demo.example`,
  first_name: first,
  last_name: 'Tester',
  role,
  status: 'ACTIVE' as const,
  job_title: null,
  department: null,
  is_company_admin: false,
  last_login_at: null,
})

export const conflictBody = (message: string, conflicts: unknown[]) => ({
  error: { code: 'INTERVIEW_CONFLICT', message, details: { conflicts }, request_id: 'req-conflict' },
})
