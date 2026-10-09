import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import {
  api,
  type ApplicationDetail,
  type ApplicationListItem,
  type JobDetail,
  type Paginated,
} from '@/lib/api'
import type {
  FeedbackIn,
  FeedbackOut,
  FeedbackSummary,
  InterviewCreate,
  InterviewDetail,
  InterviewListEntry,
  InterviewUpdate,
  StaffInterviewView,
} from './types'

/**
 * Staff-side interview hooks (list, detail, scheduling, status actions, feedback). The candidate-side hooks live in
 * `./interviews.ts`. Every key starts with 'interviews', so one `invalidateQueries({ queryKey: ['interviews'] })`
 * (also used by the candidate hooks) refreshes both audiences.
 */
export const staffInterviewKeys = {
  all: ['interviews'] as const,
  list: (f: InterviewFilters) => ['interviews', 'staff-list', f] as const,
  detail: (id: string) => ['interviews', 'detail', id] as const,
  feedback: (id: string) => ['interviews', 'feedback', id] as const,
  context: (applicationId: string) => ['interviews', 'scheduling-context', applicationId] as const,
  schedulable: (q: string) => ['interviews', 'schedulable-applications', q] as const,
}

export interface InterviewFilters {
  status: string[]
  jobId: string
  from: string
  to: string
  upcomingOnly: boolean
  sort: 'start_asc' | 'start_desc'
  page: number
  pageSize: number
}

// --- reads ---------------------------------------------------------------------------------------------------------------

export function useInterviews(filters: InterviewFilters, enabled = true) {
  return useQuery({
    queryKey: staffInterviewKeys.list(filters),
    queryFn: ({ signal }) =>
      api.get<Paginated<InterviewListEntry>>(
        '/interviews',
        {
          status: filters.status,
          job_id: filters.jobId || undefined,
          from_date: filters.from || undefined,
          to_date: filters.to || undefined,
          upcoming_only: filters.upcomingOnly || undefined,
          sort: filters.sort,
          page: filters.page,
          page_size: filters.pageSize,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
    enabled,
  })
}

/** One interview. Staff get the full record, candidates the restricted logistics view (the API decides). */
export function useInterview(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: staffInterviewKeys.detail(id ?? ''),
    queryFn: ({ signal }) => api.get<InterviewDetail>(`/interviews/${id}`, undefined, { signal }),
    enabled: Boolean(id) && enabled,
  })
}

/** Internal feedback of an interview (staff only: candidates get 403, so never enable this for them). */
export function useInterviewFeedback(id: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: staffInterviewKeys.feedback(id ?? ''),
    queryFn: ({ signal }) => api.get<FeedbackSummary>(`/interviews/${id}/feedback`, undefined, { signal }),
    enabled: Boolean(id) && enabled,
  })
}

export interface SchedulingContext {
  application: ApplicationDetail
  /** null when the job could not be read: the participant list is then not narrowed to the assigned hiring manager. */
  job: JobDetail | null
}

/** Application (candidate, job, stage, company) + job (assigned hiring manager) the scheduling dialog needs. */
export function useSchedulingContext(applicationId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: staffInterviewKeys.context(applicationId ?? ''),
    queryFn: async ({ signal }): Promise<SchedulingContext> => {
      const application = await api.get<ApplicationDetail>(`/applications/${applicationId}`, undefined, {
        signal,
      })
      const job = await api
        .get<JobDetail>(`/jobs/${application.job_id}`, undefined, { signal })
        .catch((e: unknown) => {
          if (signal.aborted) throw e
          return null
        })
      return { application, job }
    },
    enabled: Boolean(applicationId) && enabled,
    // The stage decides whether scheduling is allowed: never trust a stale one.
    staleTime: 0,
  })
}

/** Applications that can be scheduled right now (SHORTLISTED or already at the INTERVIEW stage). */
export function useSchedulableApplications(q: string, enabled: boolean) {
  return useQuery({
    queryKey: staffInterviewKeys.schedulable(q),
    queryFn: ({ signal }) =>
      api.get<Paginated<ApplicationListItem>>(
        '/applications',
        { status: ['SHORTLISTED', 'INTERVIEW'], q: q.trim() || undefined, sort: 'updated', page_size: 50 },
        { signal },
      ),
    placeholderData: keepPreviousData,
    enabled,
  })
}

// --- writes --------------------------------------------------------------------------------------------------------------

/** An interview change touches the interview lists, the application's stage/next-interview, notifications and dashboards. */
function afterChange(qc: QueryClient, detail?: InterviewDetail) {
  if (detail) qc.setQueryData(staffInterviewKeys.detail(detail.id), detail)
  void qc.invalidateQueries({ queryKey: staffInterviewKeys.all })
  void qc.invalidateQueries({ queryKey: ['applications'] })
  void qc.invalidateQueries({ queryKey: ['notifications'] })
  void qc.invalidateQueries({ queryKey: ['reports'] })
}

export function useScheduleInterview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: InterviewCreate) => api.post<StaffInterviewView>('/interviews', body),
    onSuccess: (iv) => afterChange(qc, iv),
  })
}

export function useUpdateInterview(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: InterviewUpdate) => api.patch<StaffInterviewView>(`/interviews/${id}`, body),
    onSuccess: (iv) => afterChange(qc, iv),
  })
}

export type InterviewTransition = 'cancel' | 'complete' | 'no-show' | 'confirm'

/** cancel (with an internal reason), complete, no-show (staff) and confirm (candidate). */
export function useInterviewTransition() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action, reason }: { id: string; action: InterviewTransition; reason?: string }) =>
      api.post<InterviewDetail>(`/interviews/${id}/${action}`, action === 'cancel' ? { reason } : undefined),
    onSuccess: (iv) => afterChange(qc, iv),
  })
}

/** Create (POST) or replace (PUT) the caller's own feedback. */
export function useSaveFeedback(interviewId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ values, existing }: { values: FeedbackIn; existing: boolean }) =>
      existing
        ? api.put<FeedbackOut>(`/interviews/${interviewId}/feedback`, values)
        : api.post<FeedbackOut>(`/interviews/${interviewId}/feedback`, values),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: staffInterviewKeys.feedback(interviewId) })
      void qc.invalidateQueries({ queryKey: staffInterviewKeys.all })
    },
  })
}
