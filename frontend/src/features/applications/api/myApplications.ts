import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  type ApplicationDetail,
  type ApplicationListItem,
  type ApplicationStatus,
  type components,
  type Paginated,
} from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'

/** Candidate-side application hooks. Keys live under ['applications', 'mine', …] so ['applications'] refreshes everything. */

export type HistoryEntry = components['schemas']['HistoryEntry']
export type ApplicationSort = 'newest' | 'oldest' | 'updated' | 'match'

export interface MyApplicationsParams {
  status: ApplicationStatus | ''
  sort: ApplicationSort
  page: number
  pageSize?: number
  activeOnly?: boolean
}

export const myApplicationKeys = {
  list: (p: MyApplicationsParams) => ['applications', 'mine', 'list', p] as const,
  history: (id: string) => ['applications', 'mine', 'history', id] as const,
}

/** Statuses a candidate may still withdraw from (backend: APPLIED or SCREENING). */
export const WITHDRAWABLE: readonly ApplicationStatus[] = ['APPLIED', 'SCREENING']
/** Statuses that are final (nothing more will happen). */
export const FINAL_STATUSES: readonly ApplicationStatus[] = ['HIRED', 'REJECTED', 'WITHDRAWN']

export function useMyApplications(params: MyApplicationsParams) {
  const { isCandidate } = useAuth()
  const { status, sort, page, pageSize = 10, activeOnly } = params
  return useQuery({
    queryKey: myApplicationKeys.list({ status, sort, page, pageSize, activeOnly }),
    enabled: isCandidate,
    queryFn: ({ signal }) =>
      api.get<Paginated<ApplicationListItem>>(
        '/applications',
        {
          status: status || undefined,
          sort,
          page,
          page_size: pageSize,
          active_only: activeOnly || undefined,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  })
}

/** Status timeline of one application (loaded when its history is expanded). */
export function useApplicationHistory(id: string, enabled: boolean) {
  return useQuery({
    queryKey: myApplicationKeys.history(id),
    enabled,
    queryFn: ({ signal }) => api.get<HistoryEntry[]>(`/applications/${id}/history`, undefined, { signal }),
    staleTime: 15_000,
  })
}

export function useWithdrawApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, comment }: { id: string; comment?: string }) =>
      api.post<ApplicationDetail>(`/applications/${id}/withdraw`, comment ? { comment } : {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['applications'] })
      void qc.invalidateQueries({ queryKey: ['jobs'] }) // has_applied / my_application_id flags
      void qc.invalidateQueries({ queryKey: ['recommendations'] })
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}
