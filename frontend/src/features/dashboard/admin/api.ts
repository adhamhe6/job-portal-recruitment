import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

/**
 * Platform-wide applications volume for the admin dashboard: an administrator calling the recruiter dashboard without a
 * `company_id` gets `scope: "platform"`. Only the fields used here are declared (the endpoint predates the generated schema).
 */
export interface PlatformApplications {
  scope: 'company' | 'assigned_jobs' | 'platform'
  period: { from_date: string; to_date: string; granularity: string }
  kpis: { total_applications: number; hires_in_period: number }
  applications_over_time: { bucket: string; count: number }[]
}

export function usePlatformApplications() {
  return useQuery({
    queryKey: ['admin', 'dashboard', 'applications-over-time'],
    queryFn: ({ signal }) =>
      api.get<PlatformApplications>('/reports/recruiter-dashboard', undefined, { signal }),
  })
}
