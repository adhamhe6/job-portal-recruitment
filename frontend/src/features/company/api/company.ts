import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type CompanyOut, type MemberOut } from '@/lib/api'
import { companyKeys } from '@/features/companies/api/companies'
import type { components } from '@/lib/api'

type S = components['schemas']
export type CompanyUpdate = S['CompanyUpdate']
export type MemberCreate = S['MemberCreate']
export type MemberUpdate = S['MemberUpdate']

export const myCompanyKeys = {
  mine: ['companies', 'mine'] as const,
}

/** The caller's own company, including its status (GET /companies/me). Disabled for accounts without a company. */
export function useMyCompany(enabled = true) {
  return useQuery({
    queryKey: myCompanyKeys.mine,
    queryFn: ({ signal }) => api.get<CompanyOut>('/companies/me', undefined, { signal }),
    enabled,
  })
}

export function useUpdateMyCompany(companyId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CompanyUpdate) => api.patch<CompanyOut>(`/companies/${companyId}`, body),
    onSuccess: (company) => {
      qc.setQueryData(myCompanyKeys.mine, company)
      // Name, logo and description appear on public company pages, job cards and admin lists.
      void qc.invalidateQueries({ queryKey: companyKeys.detail(companyId) })
      void qc.invalidateQueries({ queryKey: ['jobs'] })
      void qc.invalidateQueries({ queryKey: ['admin', 'companies'] })
    },
  })
}

export function useAddMember(companyId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: MemberCreate) => api.post<MemberOut>(`/companies/${companyId}/members`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: companyKeys.members(companyId) })
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
  })
}

export function useUpdateMember(companyId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, ...body }: MemberUpdate & { userId: string }) =>
      api.patch<MemberOut>(`/companies/${companyId}/members/${userId}`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: companyKeys.members(companyId) })
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
  })
}
