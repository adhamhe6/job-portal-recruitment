import type { QueryParams, Role } from '@/lib/api'
import type { ReportFilters } from '../api/types'

export interface ExportDef {
  id: string
  label: string
  description: string
  path: string
  /** `stream`: GET …?format=csv returns the file. `task`: POST …/export queues a background task, then download the result. */
  mode: 'stream' | 'task'
  usesDates: boolean
  usesJob: boolean
  /** Roles that are refused by the API for this report (the menu hides it). */
  hiddenFor?: Role[]
}

export const EXPORTS: ExportDef[] = [
  {
    id: 'funnel',
    label: 'Hiring funnel',
    description: 'Applications that reached each stage',
    path: '/reports/funnel',
    mode: 'stream',
    usesDates: true,
    usesJob: true,
  },
  {
    id: 'applications-by-status',
    label: 'Applications by status',
    description: 'Current status of applications received',
    path: '/reports/applications-by-status',
    mode: 'stream',
    usesDates: true,
    usesJob: true,
  },
  {
    id: 'pipeline-summary',
    label: 'Pipeline summary',
    description: 'Applications per stage right now, with time in stage',
    path: '/reports/pipeline-summary',
    mode: 'stream',
    usesDates: false,
    usesJob: true,
  },
  {
    id: 'job-performance',
    label: 'Job performance',
    description: 'Per-job applications, rates and days to hire (prepared in the background)',
    path: '/reports/job-performance',
    mode: 'task',
    usesDates: true,
    usesJob: false,
  },
  {
    id: 'applications-by-job',
    label: 'Applications by job',
    description: 'Applications per job with status breakdown',
    path: '/reports/applications-by-job',
    mode: 'stream',
    usesDates: true,
    usesJob: false,
  },
  {
    id: 'source-statistics',
    label: 'Application sources',
    description: 'Where applications come from',
    path: '/reports/source-statistics',
    mode: 'stream',
    usesDates: true,
    usesJob: false,
  },
  {
    id: 'top-skills',
    label: 'Skills demand and supply',
    description: 'Requested vs available skills',
    path: '/reports/top-skills',
    mode: 'stream',
    usesDates: false,
    usesJob: false,
  },
  {
    id: 'interview-statistics',
    label: 'Interview statistics',
    description: 'Outcomes, no-shows and feedback',
    path: '/reports/interview-statistics',
    mode: 'stream',
    usesDates: true,
    usesJob: false,
  },
  {
    id: 'matching-performance',
    label: 'Matching performance',
    description: 'Match score distribution and outcomes',
    path: '/reports/matching-performance',
    mode: 'stream',
    usesDates: true,
    usesJob: false,
  },
  {
    id: 'recruiter-activity',
    label: 'Recruiter activity',
    description: 'Actions per team member',
    path: '/reports/recruiter-activity',
    mode: 'stream',
    usesDates: true,
    usesJob: false,
    hiddenFor: ['HIRING_MANAGER'],
  },
]

export const exportById = (id: string) => EXPORTS.find((e) => e.id === id)

/** The query string an export sends: only the filters the report understands. */
export function exportParams(def: ExportDef, f: ReportFilters): QueryParams {
  return {
    from_date: def.usesDates ? f.from || undefined : undefined,
    to_date: def.usesDates ? f.to || undefined : undefined,
    job_id: def.usesJob ? f.jobId || undefined : undefined,
  }
}

/** Short note shown next to an export that ignores some active filters. */
export function ignoredFilters(def: ExportDef, f: ReportFilters): string | null {
  const ignored: string[] = []
  if (!def.usesDates && (f.from || f.to)) ignored.push('date range')
  if (!def.usesJob && f.jobId) ignored.push('job')
  return ignored.length ? `Ignores the ${ignored.join(' and ')} filter` : null
}
