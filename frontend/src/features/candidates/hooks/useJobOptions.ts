import { useManagedJobs } from '@/features/jobs/api/jobs'

/** The caller's company jobs (up to 100) as select options, for "match against job" pickers. */
export function useJobOptions() {
  const q = useManagedJobs({ q: '', status: 'ALL', sort: 'title', page: 1, pageSize: 100 })
  const options = (q.data?.items ?? []).map((j) => ({
    value: j.id,
    label: j.status === 'PUBLISHED' ? j.title : `${j.title} (${j.status.toLowerCase()})`,
  }))
  return { ...q, options }
}
