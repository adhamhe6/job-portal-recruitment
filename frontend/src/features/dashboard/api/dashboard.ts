import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { subDays } from 'date-fns'
import { api, type ApplicationStatus, type Paginated } from '@/lib/api'
import { dates } from '@/lib/format'

/**
 * `GET /reports/recruiter-dashboard` and `GET /interviews` are live in the backend but not part of the generated
 * `lib/api/schema.d.ts` snapshot, so the shapes the dashboard reads are declared here
 * (mirroring backend/app/schemas/report.py and schemas/interview.py).
 */
export interface FunnelStage {
  stage: ApplicationStatus
  count: number
  pct_of_applied: number | null
  pct_of_previous: number | null
  is_branch: boolean
}
export interface StatusCount {
  status: ApplicationStatus
  count: number
  percent: number
}
export interface SeriesPoint {
  bucket: string
  count: number
}
export interface JobCount {
  job_id: string
  title: string
  job_status: string
  applications: number
}
export interface TopMatch {
  candidate_id: string
  candidate_name: string
  headline: string | null
  job_id: string
  job_title: string
  score: number
  band: string
  application_id: string | null
}
export interface RecentApplication {
  id: string
  candidate_id: string
  candidate_name: string
  job_id: string
  job_title: string
  status: ApplicationStatus
  applied_at: string
  match_score: number | null
  match_band: string | null
}
export interface RecruiterDashboardData {
  scope: 'company' | 'assigned_jobs' | 'platform'
  company_id: string | null
  period: { from_date: string | null; to_date: string | null; granularity: 'day' | 'week' | 'month' | null }
  generated_at: string
  kpis: {
    active_jobs: number
    total_applications: number
    applications_in_screening: number
    shortlisted: number
    upcoming_interviews: number
    jobs_nearing_deadline: number
    avg_applications_per_job: number
    hires_in_period: number
  }
  funnel: FunnelStage[]
  applications_over_time: SeriesPoint[]
  applications_by_job: JobCount[]
  status_distribution: StatusCount[]
  top_matching_candidates: TopMatch[]
  recent_applications: RecentApplication[]
}

export interface UpcomingInterview {
  id: string
  application_id: string
  job_title: string
  candidate_name: string
  interview_type: string
  start_at: string
  end_at: string
  timezone: string
  status: string
}

export const dashboardKeys = {
  recruiter: (days: number) => ['dashboard', 'recruiter', days] as const,
  interviews: ['dashboard', 'upcoming-interviews'] as const,
}

/** Reporting window options; the backend default (30 days) is used when `days` is 30. */
export const RANGE_OPTIONS = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
]

export function useRecruiterDashboard(days: number) {
  return useQuery({
    queryKey: dashboardKeys.recruiter(days),
    queryFn: ({ signal }) =>
      api.get<RecruiterDashboardData>(
        '/reports/recruiter-dashboard',
        { from_date: dates.isoDate(subDays(new Date(), days - 1)) },
        { signal },
      ),
    placeholderData: keepPreviousData,
  })
}

/** Next interviews (SCHEDULED / CONFIRMED / RESCHEDULED, not yet ended), soonest first. */
export function useUpcomingInterviews(limit = 5) {
  return useQuery({
    queryKey: [...dashboardKeys.interviews, limit],
    queryFn: ({ signal }) =>
      api.get<Paginated<UpcomingInterview>>(
        '/interviews',
        { upcoming_only: true, sort: 'start_asc', page_size: limit },
        { signal },
      ),
  })
}
