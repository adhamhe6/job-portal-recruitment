import { useQuery } from '@tanstack/react-query'
import { api, type CompanyPublic, type MemberOut } from '@/lib/api'

export const companyKeys = {
  detail: (id: string) => ['companies', 'detail', id] as const,
  members: (id: string) => ['companies', 'members', id] as const,
}

/** Public company profile (no auth needed). */
export function useCompany(id: string | undefined) {
  return useQuery({
    queryKey: companyKeys.detail(id ?? ''),
    queryFn: ({ signal }) => api.get<CompanyPublic>(`/companies/${id}`, undefined, { signal }),
    enabled: Boolean(id),
    staleTime: 5 * 60_000,
  })
}

/** Company staff (recruiters + hiring managers); staff of that company and admins only. */
export function useCompanyMembers(companyId: string | undefined | null) {
  return useQuery({
    queryKey: companyKeys.members(companyId ?? ''),
    queryFn: ({ signal }) => api.get<MemberOut[]>(`/companies/${companyId}/members`, undefined, { signal }),
    enabled: Boolean(companyId),
    staleTime: 60_000,
  })
}
