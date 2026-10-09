import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Paginated } from '@/lib/api'
import type {
  AdminDashboardData,
  AdminTask,
  AuditEvent,
  EmbeddingRefresh,
  EmbeddingsStatus,
  MatchingStatus,
  SystemStatus,
  TaskStatus,
  TaskType,
} from './types'

/** Everything admin-related lives under ['admin', …] so one invalidation refreshes the whole console. */
export const adminKeys = {
  all: ['admin'] as const,
  dashboard: ['admin', 'dashboard'] as const,
  system: ['admin', 'system'] as const,
  tasks: (p: TaskFilters) => ['admin', 'tasks', p] as const,
  audit: (f: AuditFilters) => ['admin', 'audit', f] as const,
  embeddings: ['admin', 'embeddings'] as const,
  matching: ['admin', 'matching'] as const,
}

export interface TaskFilters {
  status: TaskStatus | ''
  type: TaskType | ''
  page: number
  pageSize: number
}

export interface AuditFilters {
  action: string
  entityType: string
  from: string
  to: string
  page: number
  pageSize: number
}

/** `refetchMs` false = no polling. Polling pauses while the tab is hidden (TanStack default). */
export interface Polling {
  refetchMs?: number | false
}

export function useAdminDashboard() {
  return useQuery({
    queryKey: adminKeys.dashboard,
    queryFn: ({ signal }) => api.get<AdminDashboardData>('/reports/admin-dashboard', undefined, { signal }),
  })
}

export function useSystemStatus({ refetchMs = false }: Polling = {}) {
  return useQuery({
    queryKey: adminKeys.system,
    queryFn: ({ signal }) => api.get<SystemStatus>('/admin/system', undefined, { signal }),
    refetchInterval: refetchMs,
  })
}

export function useAdminTasks(filters: TaskFilters, { refetchMs = false }: Polling = {}) {
  return useQuery({
    queryKey: adminKeys.tasks(filters),
    queryFn: ({ signal }) =>
      api.get<Paginated<AdminTask>>(
        '/admin/tasks',
        {
          status: filters.status,
          type: filters.type,
          page: filters.page,
          page_size: filters.pageSize,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
    refetchInterval: refetchMs,
  })
}

export function useRetryTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) => api.post<AdminTask>(`/admin/tasks/${taskId}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: adminKeys.all }),
  })
}

export function useAuditLog(filters: AuditFilters, { refetchMs = false }: Polling = {}) {
  return useQuery({
    queryKey: adminKeys.audit(filters),
    queryFn: ({ signal }) =>
      api.get<Paginated<AuditEvent>>(
        '/admin/audit',
        {
          action: filters.action.trim() || undefined,
          entity_type: filters.entityType,
          from_date: filters.from,
          to_date: filters.to,
          page: filters.page,
          page_size: filters.pageSize,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
    refetchInterval: refetchMs,
  })
}

export function useEmbeddingsStatus({ refetchMs = false }: Polling = {}) {
  return useQuery({
    queryKey: adminKeys.embeddings,
    queryFn: ({ signal }) => api.get<EmbeddingsStatus>('/admin/embeddings/status', undefined, { signal }),
    refetchInterval: refetchMs,
  })
}

export function useMatchingStatus({ refetchMs = false }: Polling = {}) {
  return useQuery({
    queryKey: adminKeys.matching,
    queryFn: ({ signal }) => api.get<MatchingStatus>('/admin/matching/status', undefined, { signal }),
    refetchInterval: refetchMs,
  })
}

/** Queue a REFRESH_EMBEDDINGS task (deduplicated server-side). */
export function useRefreshEmbeddings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<EmbeddingRefresh>('/admin/embeddings/refresh'),
    onSuccess: () => qc.invalidateQueries({ queryKey: adminKeys.all }),
  })
}
