import { http, HttpResponse, type JsonBodyType } from 'msw'
import { COMPANY_ID, makeJobListItem, page } from '@/test/fixtures'
import { server } from '@/test/server'
import type {
  ApplicationsByStatusOut,
  FunnelOut,
  InterviewStatisticsOut,
  JobPerformancePage,
  JobPerformanceRow,
  MatchingPerformanceOut,
  PipelineSummaryOut,
  SourceStatisticsPage,
  TopSkillsOut,
} from '../api/types'

const API = '/api/v1'
const period = { from_date: null, to_date: null, granularity: null }

export const funnel: FunnelOut = {
  period,
  job_id: null,
  applications: 15,
  stages: [
    { stage: 'APPLIED', count: 15, pct_of_applied: 100, pct_of_previous: null, is_branch: false },
    { stage: 'SCREENING', count: 10, pct_of_applied: 66.7, pct_of_previous: 66.7, is_branch: false },
    { stage: 'SHORTLISTED', count: 6, pct_of_applied: 40, pct_of_previous: 60, is_branch: false },
    { stage: 'INTERVIEW', count: 4, pct_of_applied: 26.7, pct_of_previous: 66.7, is_branch: false },
    { stage: 'OFFER', count: 3, pct_of_applied: 20, pct_of_previous: 75, is_branch: false },
    { stage: 'HIRED', count: 2, pct_of_applied: 13.3, pct_of_previous: 66.7, is_branch: false },
    { stage: 'REJECTED', count: 1, pct_of_applied: 6.7, pct_of_previous: null, is_branch: true },
    { stage: 'WITHDRAWN', count: 1, pct_of_applied: 6.7, pct_of_previous: null, is_branch: true },
  ],
}

export const statusBreakdown: ApplicationsByStatusOut = {
  period,
  job_id: null,
  total: 15,
  items: [
    { status: 'APPLIED', count: 4, percent: 26.7 },
    { status: 'SCREENING', count: 3, percent: 20 },
    { status: 'HIRED', count: 2, percent: 13.3 },
  ],
}

export const pipeline: PipelineSummaryOut = {
  job_id: null,
  stale_after_days: 14,
  total: 15,
  live: 11,
  closed: 4,
  stale: 1,
  stages: [
    { stage: 'APPLIED', count: 4, avg_days_in_stage: 9.6, max_days_in_stage: 17.2, stale: 1 },
    { stage: 'SCREENING', count: 3, avg_days_in_stage: 6.3, max_days_in_stage: 12.3, stale: 0 },
    { stage: 'HIRED', count: 2, avg_days_in_stage: null, max_days_in_stage: null, stale: 0 },
  ],
}

export const jobRow = (o: Partial<JobPerformanceRow> = {}): JobPerformanceRow => ({
  job_id: 'job-1',
  title: 'Senior Backend Engineer',
  job_status: 'PUBLISHED',
  published_at: '2026-09-18T00:00:00Z',
  applications: 7,
  reached_shortlist: 2,
  hires: 1,
  shortlist_rate: 0.2857,
  hire_rate: 0.1429,
  avg_days_to_first_status_change: 2.46,
  avg_days_to_hire: 12,
  avg_match_score: 0.6534,
  applicants_scored: 7,
  ...o,
})

export const jobPerformance = (
  items = [
    jobRow(),
    jobRow({ job_id: 'job-2', title: 'Data Analyst', applications: 2, hires: 0, avg_days_to_hire: null }),
  ],
): JobPerformancePage => ({
  items,
  page: 1,
  page_size: 10,
  total: items.length,
  pages: 1,
  period,
  note: 'Job views are not tracked; performance starts at the application.',
})

export const sources: SourceStatisticsPage = {
  items: [
    {
      source: 'DIRECT',
      applications: 12,
      share: 0.8,
      reached_shortlist: 5,
      hires: 2,
      shortlist_rate: 0.42,
      hire_rate: 0.17,
    },
    {
      source: 'REFERRAL',
      applications: 3,
      share: 0.2,
      reached_shortlist: 1,
      hires: 0,
      shortlist_rate: 0.33,
      hire_rate: 0,
    },
  ],
  page: 1,
  page_size: 20,
  total: 2,
  pages: 1,
  period,
}

export const topSkills: TopSkillsOut = {
  scope: 'company',
  jobs_considered: 5,
  applicants_considered: 12,
  requested: [{ skill_id: 's1', skill: 'Python', jobs: 3, required_in_jobs: 2, preferred_in_jobs: 1 }],
  available: [{ skill_id: 's1', skill: 'Python', candidates: 10 }],
}

export const interviewStats: InterviewStatisticsOut = {
  period,
  total: 8,
  by_status: { SCHEDULED: 2, COMPLETED: 5, NO_SHOW: 1 },
  by_type: { TECHNICAL: 5, PANEL: 3 },
  avg_duration_minutes: 55,
  held_or_missed: 6,
  no_show_rate: 0.1667,
  cancellation_rate: 0,
  feedback: {
    entries: 4,
    interviews_with_feedback: 3,
    average_rating: 4.25,
    recommendations: { HIRE: 3, NO_HIRE: 1 },
  },
}

export const matching: MatchingPerformanceOut = {
  period,
  scored_pairs: 125,
  all_scored_distribution: [{ band: 'STRONG', count: 12, percent: 9.6 }],
  applicant_distribution: [
    { band: 'STRONG', count: 8, percent: 53.3 },
    { band: 'GOOD', count: 4, percent: 26.7 },
  ],
  avg_score_by_outcome: [
    { outcome: 'HIRED', applications: 2, avg_score: 1 },
    { outcome: 'REJECTED', applications: 1, avg_score: 0.4732 },
  ],
  hired_minus_rejected: 0.5268,
  top10: { applicants: 15, applicants_with_score: 15, applicants_in_top10: 15, pct_in_top10: 100 },
  notes: [
    'Scores rank candidates against a job; they are a relevance aid, not a prediction of hiring success.',
  ],
}

/** Register default handlers for every report endpoint; returns the query strings each path received. */
export function mockReports(overrides: Record<string, () => Response | Promise<Response>> = {}) {
  const calls: Record<string, URLSearchParams[]> = {}
  const route = (path: string, data: JsonBodyType) =>
    http.get(`${API}/reports/${path}`, ({ request }) => {
      const url = new URL(request.url)
      ;(calls[path] ??= []).push(url.searchParams)
      if (overrides[path]) return overrides[path]()
      return HttpResponse.json(data)
    })
  server.use(
    route('funnel', funnel),
    route('applications-by-status', statusBreakdown),
    route('pipeline-summary', pipeline),
    route('job-performance', jobPerformance()),
    route('source-statistics', sources),
    route('top-skills', topSkills),
    route('interview-statistics', interviewStats),
    route('matching-performance', matching),
    http.get(`${API}/jobs`, () =>
      HttpResponse.json(
        page([
          makeJobListItem({ id: 'job-1', title: 'Senior Backend Engineer' }),
          makeJobListItem({ id: 'job-2', title: 'Data Analyst' }),
        ]),
      ),
    ),
    http.get(`${API}/companies/${COMPANY_ID}/members`, () => HttpResponse.json([])),
  )
  return calls
}
export const lastCall = (calls: Record<string, URLSearchParams[]>, path: string) =>
  calls[path]![calls[path]!.length - 1]!
