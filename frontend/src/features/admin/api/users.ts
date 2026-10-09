import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Paginated } from '@/lib/api'
import { adminKeys } from './admin'
import type { AdminUser, AdminUserCreate, AdminUserUpdate } from './types'

export interface UserFilters {
  q: string
  role: string
  status: string
  companyId: string
  page: number
  pageSize: number
}

export const userKeys = {
  all: ['admin', 'users'] as const,
  list: (f: UserFilters) => ['admin', 'users', 'list', f] as const,
}

export function useAdminUsers(f: UserFilters) {
  return useQuery({
    queryKey: userKeys.list(f),
    queryFn: ({ signal }) =>
      api.get<Paginated<AdminUser>>(
        '/users',
        {
          q: f.q.trim() || undefined,
          role: f.role,
          status: f.status,
          company_id: f.companyId,
          page: f.page,
          page_size: f.pageSize,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
  })
}

export function useCreateUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AdminUserCreate) => api.post<AdminUser>('/users', body),
    onSuccess: () => {
      // Creating a user changes user lists, company member lists and the dashboard counters.
      void qc.invalidateQueries({ queryKey: userKeys.all })
      void qc.invalidateQueries({ queryKey: adminKeys.dashboard })
      void qc.invalidateQueries({ queryKey: ['companies', 'members'] })
    },
  })
}

export function useUpdateUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: AdminUserUpdate & { id: string }) =>
      api.patch<AdminUser>(`/users/${id}`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: userKeys.all })
      void qc.invalidateQueries({ queryKey: adminKeys.dashboard })
      void qc.invalidateQueries({ queryKey: ['companies', 'members'] })
    },
  })
}
