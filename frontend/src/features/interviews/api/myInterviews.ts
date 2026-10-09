import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Paginated } from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'

/**
 * Candidate view of interviews. The checked-in OpenAPI snapshot predates the interview module, so this mirrors
 * `backend/app/schemas/interview.py::CandidateInterviewView` by hand (candidates never receive notes, feedback or
 * staff contact data). Replace with the generated type after the next `npm run gen:api`.
 */
export type InterviewType = 'PHONE_SCREEN' | 'TECHNICAL' | 'BEHAVIORAL' | 'PANEL' | 'ONSITE' | 'FINAL'
export type InterviewStatus =
  'SCHEDULED' | 'CONFIRMED' | 'RESCHEDULED' | 'COMPLETED' | 'CANCELLED' | 'NO_SHOW'

export interface CandidateInterview {
  audience: 'candidate'
  id: string
  application_id: string
  job_id: string
  job_title: string
  company_name: string
  interview_type: InterviewType
  start_at: string
  end_at: string
  /** start_at rendered in the interview's own timezone (ISO 8601 with offset). */
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

export type InterviewView = 'upcoming' | 'past' | 'all'

export const interviewKeys = {
  all: ['interviews'] as const,
  list: (p: { view: InterviewView; page: number; pageSize: number }) => ['interviews', 'mine', p] as const,
}

const PAST_STATUSES: InterviewStatus[] = ['COMPLETED', 'CANCELLED', 'NO_SHOW']

export function useMyInterviews(params: { view: InterviewView; page: number; pageSize?: number }) {
  const { isCandidate } = useAuth()
  const { view, page, pageSize = 10 } = params
  return useQuery({
    queryKey: interviewKeys.list({ view, page, pageSize }),
    enabled: isCandidate,
    queryFn: ({ signal }) =>
      api.get<Paginated<CandidateInterview>>(
        '/interviews',
        {
          upcoming_only: view === 'upcoming' || undefined,
          status: view === 'past' ? PAST_STATUSES : undefined,
          sort: view === 'upcoming' ? 'start_asc' : 'start_desc',
          page,
          page_size: pageSize,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  })
}

/** Candidate confirms attendance (SCHEDULED / RESCHEDULED → CONFIRMED; idempotent). */
export function useConfirmInterview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<CandidateInterview>(`/interviews/${id}/confirm`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: interviewKeys.all })
      void qc.invalidateQueries({ queryKey: ['applications'] })
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}
