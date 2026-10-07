import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import {
  api,
  type JobCreate,
  type JobDetail,
  type JobListItem,
  type JobPublic,
  type JobStats,
  type JobUpdate,
  type Paginated,
  type QueryParams,
} from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { toSearchQuery, type JobSearchState } from '../lib/filters'
import type { LifecycleAction } from '../lib/lifecycle'

/**
 * Query keys. Everything job-related lives under ['jobs', …] so a single `invalidateQueries({ queryKey: ['jobs'] })`
 * refreshes lists, details and stats after any mutation.
 */
export const jobKeys = {
  all: ['jobs'] as const,
  search: (f: JobSearchState) => ['jobs', 'search', f] as const,
  featured: ['jobs', 'search', 'featured'] as const,
  saved: (page: number) => ['jobs', 'saved', page] as const,
  manage: (p: ManageJobsParams) => ['jobs', 'manage', p] as const,
  detail: (id: string) => ['jobs', 'detail', id] as const,
  stats: (id: string) => ['jobs', 'stats', id] as const,
}

/** The detail endpoint returns the staff shape (JobDetail) to the owning company and the public shape otherwise. */
export type JobView = JobDetail | JobPublic
export const isStaffView = (job: JobView): job is JobDetail => 'allowed_transitions' in job

// --- reads --------------------------------------------------------------------------------------------------------------

export function useJobSearch(filters: JobSearchState) {
  return useQuery({
    queryKey: jobKeys.search(filters),
    queryFn: ({ signal }) =>
      api.get<Paginated<JobListItem>>('/search/jobs', toSearchQuery(filters), { signal }),
    placeholderData: keepPreviousData,
  })
}

/** Newest published jobs for the landing page. */
export function useFeaturedJobs(limit = 6) {
  return useQuery({
    queryKey: [...jobKeys.featured, limit],
    queryFn: ({ signal }) =>
      api.get<Paginated<JobListItem>>('/search/jobs', { sort: 'newest', page_size: limit }, { signal }),
    staleTime: 60_000,
  })
}

export function useSavedJobs(page: number, pageSize = 10) {
  return useQuery({
    queryKey: jobKeys.saved(page),
    queryFn: ({ signal }) =>
      api.get<Paginated<JobListItem>>('/candidates/me/saved-jobs', { page, page_size: pageSize }, { signal }),
    placeholderData: keepPreviousData,
  })
}

export interface ManageJobsParams {
  q: string
  status: string
  sort: string
  page: number
  pageSize: number
  companyId?: string
}

export function useManagedJobs(p: ManageJobsParams) {
  return useQuery({
    queryKey: jobKeys.manage(p),
    queryFn: ({ signal }) =>
      api.get<Paginated<JobListItem>>(
        '/jobs',
        {
          q: p.q.trim() || undefined,
          status: p.status === 'ALL' ? undefined : p.status,
          sort: p.sort,
          page: p.page,
          page_size: p.pageSize,
          company_id: p.companyId || undefined,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
  })
}

export function useJob(id: string | undefined) {
  return useQuery({
    queryKey: jobKeys.detail(id ?? ''),
    queryFn: ({ signal }) => api.get<JobView>(`/jobs/${id}`, undefined, { signal }),
    enabled: Boolean(id),
  })
}

export function useJobStats(id: string | undefined, enabled = true) {
  const { can } = useAuth()
  return useQuery({
    queryKey: jobKeys.stats(id ?? ''),
    queryFn: ({ signal }) => api.get<JobStats>(`/jobs/${id}/stats`, undefined, { signal }),
    enabled: Boolean(id) && enabled && can('view_company_jobs'),
  })
}

// --- saved-job toggle (optimistic across every cached list/detail) --------------------------------------------------------

function patchSaved(qc: QueryClient, jobId: string, saved: boolean) {
  qc.setQueriesData<Paginated<JobListItem>>({ queryKey: ['jobs', 'search'] }, (old) =>
    old ? { ...old, items: old.items.map((j) => (j.id === jobId ? { ...j, is_saved: saved } : j)) } : old,
  )
  qc.setQueriesData<JobView>({ queryKey: ['jobs', 'detail'], exact: false }, (old) =>
    old && old.id === jobId && !isStaffView(old) ? { ...old, is_saved: saved } : old,
  )
  if (!saved) {
    // Un-saving removes the row from the "Saved" list immediately.
    qc.setQueriesData<Paginated<JobListItem>>({ queryKey: ['jobs', 'saved'] }, (old) =>
      old
        ? {
            ...old,
            items: old.items.filter((j) => j.id !== jobId),
            total: Math.max(0, old.total - (old.items.some((j) => j.id === jobId) ? 1 : 0)),
          }
        : old,
    )
  }
}

export function useToggleSaveJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ jobId, save }: { jobId: string; save: boolean }) =>
      save ? api.put(`/jobs/${jobId}/save`) : api.delete(`/jobs/${jobId}/save`),
    onMutate: async ({ jobId, save }) => {
      await qc.cancelQueries({ queryKey: jobKeys.all })
      const snapshot = qc.getQueriesData({ queryKey: jobKeys.all })
      patchSaved(qc, jobId, save)
      return { snapshot }
    },
    onError: (_e, _v, ctx) => ctx?.snapshot.forEach(([key, data]) => qc.setQueryData(key, data)),
    onSettled: (_d, _e, { save }) => {
      void qc.invalidateQueries({ queryKey: ['jobs', 'saved'] })
      if (save) void qc.invalidateQueries({ queryKey: ['jobs', 'search'] })
    },
  })
}

// --- staff mutations ---------------------------------------------------------------------------------------------------------

const invalidateJobs = (qc: QueryClient) => qc.invalidateQueries({ queryKey: jobKeys.all })

export function useCreateJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ body, companyId }: { body: JobCreate; companyId?: string }) =>
      api.post<JobDetail>('/jobs', body, { query: companyId ? { company_id: companyId } : undefined }),
    onSuccess: () => invalidateJobs(qc),
  })
}

export function useUpdateJob(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: JobUpdate) => api.patch<JobDetail>(`/jobs/${id}`, body),
    onSuccess: (job) => {
      qc.setQueryData(jobKeys.detail(id), job)
      return invalidateJobs(qc)
    },
  })
}

export function useDeleteJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/jobs/${id}`),
    onSuccess: () => invalidateJobs(qc),
  })
}

export function useJobTransition() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action, reason }: { id: string; action: LifecycleAction; reason?: string }) =>
      api.post<JobDetail>(`/jobs/${id}/${action}`, reason?.trim() ? { reason: reason.trim() } : undefined),
    onSuccess: (job, { id }) => {
      qc.setQueryData(jobKeys.detail(id), job)
      return invalidateJobs(qc)
    },
  })
}

export type { QueryParams }
