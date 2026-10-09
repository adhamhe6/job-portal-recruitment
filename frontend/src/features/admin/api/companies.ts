import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Paginated } from '@/lib/api'
import { adminKeys } from './admin'
import type { AdminCompany, AdminCompanyCreate, AdminCompanyUpdate } from './types'

export interface CompanyFilters {
  q: string
  status: string
  page: number
  pageSize: number
}

export const adminCompanyKeys = {
  all: ['admin', 'companies'] as const,
  list: (f: CompanyFilters) => ['admin', 'companies', 'list', f] as const,
  options: ['admin', 'companies', 'options'] as const,
}

export function useAdminCompanies(f: CompanyFilters) {
  return useQuery({
    queryKey: adminCompanyKeys.list(f),
    queryFn: ({ signal }) =>
      api.get<Paginated<AdminCompany>>(
        '/companies',
        { q: f.q.trim() || undefined, status: f.status, page: f.page, page_size: f.pageSize },
        { signal },
      ),
    placeholderData: keepPreviousData,
  })
}

/** Up to 100 companies for pickers (user filters / forms) and id -> name lookups. */
export function useCompanyOptions() {
  return useQuery({
    queryKey: adminCompanyKeys.options,
    queryFn: ({ signal }) => api.get<Paginated<AdminCompany>>('/companies', { page_size: 100 }, { signal }),
    staleTime: 60_000,
    select: (p) => p.items,
  })
}

function useInvalidateCompanies() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: adminCompanyKeys.all })
    void qc.invalidateQueries({ queryKey: adminKeys.dashboard })
    // Company name/logo/status feed job lists and public company pages.
    void qc.invalidateQueries({ queryKey: ['companies'] })
    void qc.invalidateQueries({ queryKey: ['jobs'] })
  }
}

export function useUpdateAdminCompany() {
  const invalidate = useInvalidateCompanies()
  return useMutation({
    mutationFn: ({ id, ...body }: AdminCompanyUpdate & { id: string }) =>
      api.patch<AdminCompany>(`/companies/${id}`, body),
    onSuccess: invalidate,
  })
}

export function useCreateCompany() {
  const invalidate = useInvalidateCompanies()
  return useMutation({
    mutationFn: (body: AdminCompanyCreate) => api.post<AdminCompany>('/companies', body),
    onSuccess: invalidate,
  })
}
