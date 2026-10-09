/**
 * Report API shapes. `/reports/*` is live in the backend but was not part of the generated `lib/api/schema.d.ts`
 * snapshot when this module was written, so the shapes are declared here (mirroring `backend/app/schemas/report.py`).
 */
import type { ApplicationStatus, JobStatus } from '@/lib/api'

export interface Period {
  from_date: string | null
  to_date: string | null
  granularity: 'day' | 'week' | 'month' | null
}

export interface FunnelStage {
  stage: ApplicationStatus
  count: number
  pct_of_applied: number | null
  pct_of_previous: number | null
  is_branch: boolean
}

export interface FunnelOut {
  period: Period
  job_id: string | null
  applications: number
  stages: FunnelStage[]
}

export interface StatusCount {
  status: ApplicationStatus
  count: number
  percent: number
}

export interface ApplicationsByStatusOut {
  period: Period
  job_id: string | null
  total: number
  items: StatusCount[]
}

export interface PipelineStageRow {
  stage: ApplicationStatus
  count: number
  avg_days_in_stage: number | null
  max_days_in_stage: number | null
  stale: number
}

export interface PipelineSummaryOut {
  job_id: string | null
  stale_after_days: number
  total: number
  live: number
  closed: number
  stale: number
  stages: PipelineStageRow[]
}

export type JobPerformanceSort =
  | 'applications'
  | 'title'
  | 'shortlist_rate'
  | 'hire_rate'
  | 'avg_days_to_hire'
  | 'avg_match_score'

export interface JobPerformanceRow {
  job_id: string
  title: string
  job_status: JobStatus
  published_at: string | null
  applications: number
  reached_shortlist: number
  hires: number
  shortlist_rate: number | null
  hire_rate: number | null
  avg_days_to_first_status_change: number | null
  avg_days_to_hire: number | null
  avg_match_score: number | null
  applicants_scored: number
}

export interface JobPerformancePage {
  items: JobPerformanceRow[]
  page: number
  page_size: number
  total: number
  pages: number
  period: Period
  note: string
}

export interface SourceStatRow {
  source: string
  applications: number
  share: number
  reached_shortlist: number
  hires: number
  shortlist_rate: number | null
  hire_rate: number | null
}

export interface SourceStatisticsPage {
  items: SourceStatRow[]
  page: number
  page_size: number
  total: number
  pages: number
  period: Period
}

export interface SkillDemand {
  skill_id: string
  skill: string
  jobs: number
  required_in_jobs: number
  preferred_in_jobs: number
}

export interface SkillSupply {
  skill_id: string
  skill: string
  candidates: number
}

export interface TopSkillsOut {
  scope: 'company' | 'assigned_jobs' | 'platform'
  jobs_considered: number
  applicants_considered: number
  requested: SkillDemand[]
  available: SkillSupply[]
}

export interface InterviewStatisticsOut {
  period: Period
  total: number
  by_status: Record<string, number>
  by_type: Record<string, number>
  avg_duration_minutes: number | null
  held_or_missed: number
  no_show_rate: number | null
  cancellation_rate: number | null
  feedback: {
    entries: number
    interviews_with_feedback: number
    average_rating: number | null
    recommendations: Record<string, number>
  }
}

export interface BandCount {
  band: string
  count: number
  percent: number
}

export interface MatchingPerformanceOut {
  period: Period
  scored_pairs: number
  all_scored_distribution: BandCount[]
  applicant_distribution: BandCount[]
  avg_score_by_outcome: {
    outcome: 'HIRED' | 'REJECTED' | 'WITHDRAWN' | 'IN_PROGRESS'
    applications: number
    avg_score: number | null
  }[]
  hired_minus_rejected: number | null
  top10: {
    applicants: number
    applicants_with_score: number
    applicants_in_top10: number
    pct_in_top10: number | null
  }
  notes: string[]
}

/** Date window + optional job shared by every report. */
export interface ReportFilters {
  from: string
  to: string
  jobId: string
}
