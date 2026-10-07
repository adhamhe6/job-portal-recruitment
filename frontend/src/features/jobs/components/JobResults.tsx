import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ErrorState } from '@/components/common/States'
import { Pagination } from '@/components/ui/pagination'
import type { JobListItem, Paginated } from '@/lib/api'
import { cn } from '@/lib/utils'
import { JobCard, JobCardSkeleton } from './JobCard'

/**
 * Standard rendering of a paginated job list: skeletons while loading, retryable error, caller-supplied empty state,
 * cards, and pagination. Keeps the previous page visible (dimmed) while the next one loads.
 */
export function JobResults({
  query,
  empty,
  onPageChange,
  highlightSkills,
  skeletons = 5,
  label = 'jobs',
}: {
  query: UseQueryResult<Paginated<JobListItem>>
  empty: ReactNode
  onPageChange: (page: number) => void
  highlightSkills?: string[]
  skeletons?: number
  label?: string
}) {
  if (query.isPending) {
    return (
      <div className="space-y-3" role="status" aria-busy="true" aria-label="Loading jobs">
        {Array.from({ length: skeletons }).map((_, i) => (
          <JobCardSkeleton key={i} />
        ))}
      </div>
    )
  }
  if (query.isError && !query.data) return <ErrorState error={query.error} onRetry={() => query.refetch()} title="We couldn't load jobs" />
  const data = query.data
  if (!data || data.items.length === 0) return <>{empty}</>
  return (
    <div>
      {query.isError && <ErrorState compact error={query.error} onRetry={() => query.refetch()} title="Showing earlier results" />}
      <ul className={cn('space-y-3 transition-opacity', query.isPlaceholderData && 'opacity-60')} aria-busy={query.isPlaceholderData || undefined}>
        {data.items.map((job) => (
          <li key={job.id}>
            <JobCard job={job} highlightSkills={highlightSkills} />
          </li>
        ))}
      </ul>
      <Pagination page={data.page} pages={data.pages} total={data.total} pageSize={data.page_size} onPageChange={onPageChange} label={label} className="mt-4" />
    </div>
  )
}
