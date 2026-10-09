import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, type QueryParams } from '@/lib/api'
import type {
  ApplicationsByStatusOut,
  FunnelOut,
  InterviewStatisticsOut,
  JobPerformancePage,
  JobPerformanceSort,
  MatchingPerformanceOut,
  PipelineSummaryOut,
  ReportFilters,
  SourceStatisticsPage,
  TopSkillsOut,
} from './types'

/** Every report lives under ['reports', name, params] so one invalidation refreshes them all (interview/application writes do). */
export const reportKeys = {
  all: ['reports'] as const,
  one: (name: string, params: unknown) => ['reports', name, params] as const,
}

/** Query-string params shared by the date-windowed reports. */
export const dateParams = (f: ReportFilters): QueryParams => ({
  from_date: f.from || undefined,
  to_date: f.to || undefined,
})

export const dateAndJobParams = (f: ReportFilters): QueryParams => ({
  ...dateParams(f),
  job_id: f.jobId || undefined,
})

function useReport<T>(name: string, path: string, params: QueryParams, enabled: boolean) {
  return useQuery({
    queryKey: reportKeys.one(name, params),
    queryFn: ({ signal }) => api.get<T>(path, params, { signal }),
    placeholderData: keepPreviousData,
    enabled,
  })
}

export const useFunnel = (f: ReportFilters, enabled = true) =>
  useReport<FunnelOut>('funnel', '/reports/funnel', dateAndJobParams(f), enabled)

export const useStatusBreakdown = (f: ReportFilters, enabled = true) =>
  useReport<ApplicationsByStatusOut>(
    'applications-by-status',
    '/reports/applications-by-status',
    dateAndJobParams(f),
    enabled,
  )

/** A current snapshot: only the job filter applies. */
export const usePipelineSummary = (f: ReportFilters, enabled = true) =>
  useReport<PipelineSummaryOut>(
    'pipeline-summary',
    '/reports/pipeline-summary',
    { job_id: f.jobId || undefined },
    enabled,
  )

export interface JobPerformanceParams {
  page: number
  pageSize: number
  sort: JobPerformanceSort
  order: 'asc' | 'desc'
}

export const useJobPerformance = (f: ReportFilters, p: JobPerformanceParams, enabled = true) =>
  useReport<JobPerformancePage>(
    'job-performance',
    '/reports/job-performance',
    { ...dateParams(f), page: p.page, page_size: p.pageSize, sort: p.sort, order: p.order },
    enabled,
  )

export const useSourceStatistics = (f: ReportFilters, enabled = true) =>
  useReport<SourceStatisticsPage>(
    'source-statistics',
    '/reports/source-statistics',
    { ...dateParams(f), page_size: 20 },
    enabled,
  )

/** Not date-windowed: demand = published jobs, supply = applicants' confirmed skills. */
export const useTopSkills = (enabled = true) =>
  useReport<TopSkillsOut>('top-skills', '/reports/top-skills', { limit: 10 }, enabled)

export const useInterviewStatistics = (f: ReportFilters, enabled = true) =>
  useReport<InterviewStatisticsOut>('interview-statistics', '/reports/interview-statistics', dateParams(f), enabled)

export const useMatchingPerformance = (f: ReportFilters, enabled = true) =>
  useReport<MatchingPerformanceOut>('matching-performance', '/reports/matching-performance', dateParams(f), enabled)
