import { useQuery } from '@tanstack/react-query'
import { api, type ApplicationListItem, type ApplicationStatus, type Paginated } from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'

export const DASHBOARD_APPLICATION_LIMIT = 100

/** All of the candidate's applications (first 100), used for status counts and the "recent" list. */
export function useDashboardApplications() {
  const { isCandidate } = useAuth()
  return useQuery({
    queryKey: ['applications', 'mine', 'dashboard'] as const,
    enabled: isCandidate,
    queryFn: ({ signal }) =>
      api.get<Paginated<ApplicationListItem>>(
        '/applications',
        { sort: 'updated', page_size: DASHBOARD_APPLICATION_LIMIT },
        { signal },
      ),
    staleTime: 30_000,
  })
}

export const STATUS_ORDER: ApplicationStatus[] = [
  'APPLIED',
  'SCREENING',
  'SHORTLISTED',
  'INTERVIEW',
  'OFFER',
  'HIRED',
  'REJECTED',
  'WITHDRAWN',
]

export function countByStatus(items: ApplicationListItem[]): Record<ApplicationStatus, number> {
  const counts = Object.fromEntries(STATUS_ORDER.map((s) => [s, 0])) as Record<ApplicationStatus, number>
  for (const a of items) counts[a.status] = (counts[a.status] ?? 0) + 1
  return counts
}
