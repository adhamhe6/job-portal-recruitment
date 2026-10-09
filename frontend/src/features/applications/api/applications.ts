import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import {
  api,
  ApiError,
  type ApplicationCreate,
  type ApplicationDetail,
  type ApplicationListItem,
  type ApplicationStatus,
  type components,
  type Paginated,
} from '@/lib/api'
import { staffTargets } from '../lib/workflow'

export type ApplicationNote = components['schemas']['NoteOut']
export type MatchDetail = components['schemas']['MatchDetail']

/** Staff view of an interview in `GET /interviews` (not yet in the generated schema; minimal shape used here). */
export interface ApplicationInterview {
  id: string
  application_id: string
  interview_type: string
  start_at: string
  end_at: string
  timezone: string
  status: string
  location: string | null
  meeting_url: string | null
  participants?: { name: string; role: string }[]
}

export interface ApplicationFilters {
  jobId: string
  status: string
  q: string
  sort: string
  page: number
  pageSize: number
}

export const applicationKeys = {
  all: ['applications'] as const,
  list: (f: ApplicationFilters) => ['applications', 'list', f] as const,
  lists: ['applications', 'list'] as const,
  detail: (id: string) => ['applications', 'detail', id] as const,
  notes: (id: string) => ['applications', 'notes', id] as const,
  match: (jobId: string, candidateId: string) => ['applications', 'match', jobId, candidateId] as const,
  interviews: (id: string) => ['applications', 'interviews', id] as const,
}

// --- reads --------------------------------------------------------------------------------------------------------------

/** GET /applications — staff list (recruiters: company; hiring managers: assigned jobs; admins: all). */
export function useApplications(f: ApplicationFilters) {
  return useQuery({
    queryKey: applicationKeys.list(f),
    queryFn: ({ signal }) =>
      api.get<Paginated<ApplicationListItem>>(
        '/applications',
        {
          job_id: f.jobId || undefined,
          status: f.status || undefined,
          q: f.q.trim() || undefined,
          sort: f.sort,
          page: f.page,
          page_size: f.pageSize,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
  })
}

/** GET /applications/{id} — role-aware: candidates get a redacted view (no match, no rejection reason, anonymised actors). */
export function useApplication(id: string | undefined) {
  return useQuery({
    queryKey: applicationKeys.detail(id ?? ''),
    queryFn: ({ signal }) => api.get<ApplicationDetail>(`/applications/${id}`, undefined, { signal }),
    enabled: Boolean(id),
  })
}

/** GET /applications/{id}/notes — internal, hiring staff only (the hook never fires for candidates). */
export function useApplicationNotes(id: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: applicationKeys.notes(id ?? ''),
    queryFn: ({ signal }) => api.get<ApplicationNote[]>(`/applications/${id}/notes`, undefined, { signal }),
    enabled: Boolean(id) && enabled,
  })
}

/** GET /matches/jobs/{job}/candidates/{cand} — resolves to null when no match was computed (404) or it is not visible (403). */
export function useApplicationMatch(
  jobId: string | undefined,
  candidateId: string | undefined,
  enabled: boolean,
) {
  return useQuery({
    queryKey: applicationKeys.match(jobId ?? '', candidateId ?? ''),
    enabled: Boolean(jobId && candidateId) && enabled,
    queryFn: async ({ signal }) => {
      try {
        return await api.get<MatchDetail>(`/matches/jobs/${jobId}/candidates/${candidateId}`, undefined, {
          signal,
        })
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 403)) return null
        throw e
      }
    },
  })
}

/** GET /interviews?application_id= — interviews of one application (staff). */
export function useApplicationInterviews(applicationId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: applicationKeys.interviews(applicationId ?? ''),
    enabled: Boolean(applicationId) && enabled,
    queryFn: ({ signal }) =>
      api.get<Paginated<ApplicationInterview>>(
        '/interviews',
        { application_id: applicationId, page_size: 50, sort: 'start_desc' },
        { signal },
      ),
  })
}

// --- writes -------------------------------------------------------------------------------------------------------------

/** POST /applications — apply to a job (used by the apply dialog on the job page). */
export function useApplyToJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ApplicationCreate) => api.post<ApplicationDetail>('/applications', body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: applicationKeys.all })
      void qc.invalidateQueries({ queryKey: ['jobs'] }) // has_applied / my_application_id flags
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}

/** Everything a stage change / withdrawal can make stale. */
function invalidateAfterStageChange(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: applicationKeys.all })
  void qc.invalidateQueries({ queryKey: ['dashboard'] })
  void qc.invalidateQueries({ queryKey: ['reports'] })
  void qc.invalidateQueries({ queryKey: ['jobs', 'stats'] })
  void qc.invalidateQueries({ queryKey: ['interviews'] })
  void qc.invalidateQueries({ queryKey: ['notifications'] })
}

export interface StatusChangeInput {
  id: string
  status: ApplicationStatus
  comment?: string
}

type ListSnapshot = [readonly unknown[], Paginated<ApplicationListItem> | undefined][]

/**
 * POST /applications/{id}/status. Optimistic: the card/row/detail jumps to the new stage immediately; on any error
 * the snapshot is restored (and the caller shows the server's explanation). The server response is written back to
 * the detail cache, then everything application-related is refetched.
 */
export function useChangeStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status, comment }: StatusChangeInput) =>
      api.post<ApplicationDetail>(`/applications/${id}/status`, {
        status,
        comment: comment?.trim() ? comment.trim() : null,
      }),
    onMutate: async ({ id, status, comment }) => {
      await qc.cancelQueries({ queryKey: applicationKeys.all })
      const lists: ListSnapshot = qc.getQueriesData<Paginated<ApplicationListItem>>({
        queryKey: applicationKeys.lists,
      })
      const detail = qc.getQueryData<ApplicationDetail>(applicationKeys.detail(id))
      const now = new Date().toISOString()
      qc.setQueriesData<Paginated<ApplicationListItem>>({ queryKey: applicationKeys.lists }, (old) =>
        old
          ? {
              ...old,
              items: old.items.map((a) => (a.id === id ? { ...a, status, status_changed_at: now } : a)),
            }
          : old,
      )
      if (detail) {
        qc.setQueryData<ApplicationDetail>(applicationKeys.detail(id), {
          ...detail,
          status,
          status_changed_at: now,
          allowed_next_statuses: staffTargets(status),
          rejection_reason: status === 'REJECTED' ? (comment?.trim() ?? detail.rejection_reason) : null,
        })
      }
      return { lists, detail }
    },
    onError: (_e, { id }, ctx) => {
      ctx?.lists.forEach(([key, data]) => qc.setQueryData(key, data))
      if (ctx?.detail) qc.setQueryData(applicationKeys.detail(id), ctx.detail)
    },
    onSuccess: (detail, { id }) => {
      qc.setQueryData(applicationKeys.detail(id), detail)
    },
    onSettled: () => invalidateAfterStageChange(qc),
  })
}

/** POST /applications/{id}/withdraw (candidates, only before shortlisting). */
export function useWithdrawApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, comment }: { id: string; comment?: string }) =>
      api.post<ApplicationDetail>(`/applications/${id}/withdraw`, {
        comment: comment?.trim() ? comment.trim() : null,
      }),
    onSuccess: (detail) => {
      qc.setQueryData(applicationKeys.detail(detail.id), detail)
      invalidateAfterStageChange(qc)
    },
  })
}

/** POST /applications/{id}/notes — newest first, so the new note is prepended to the cache and the list refetched. */
export function useAddNote(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: string) => api.post<ApplicationNote>(`/applications/${id}/notes`, { body }),
    onSuccess: (note) => {
      qc.setQueryData<ApplicationNote[]>(applicationKeys.notes(id), (old) => [note, ...(old ?? [])])
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: applicationKeys.notes(id) }),
  })
}
