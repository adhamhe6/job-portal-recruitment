import { ArrowRight, Clock, MapPin, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Skeleton } from '@/components/ui/skeleton'
import { useJobStats } from '@/features/jobs/api/jobs'
import type { JobListItem } from '@/lib/api'
import { dates, fmt } from '@/lib/format'
import { pluralize } from '@/lib/utils'
import { paths } from '@/routes/paths'

/** A job in the picker, with its match summary (GET /jobs/{id}/stats): applicants, matches computed, last run. */
export function JobMatchCard({ job }: { job: JobListItem }) {
  const stats = useJobStats(job.id)
  const s = stats.data
  return (
    <article className="relative rounded-xl border bg-card p-4 shadow-xs transition-[box-shadow,border-color] hover:border-primary/30 hover:shadow-md focus-within:border-primary/40 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-base font-semibold break-words">
            <Link
              to={paths.matchingJob(job.id)}
              className="rounded-sm after:absolute after:inset-0 after:content-[''] hover:text-primary"
            >
              {job.title}
            </Link>
          </h3>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
            {job.department && <span>{job.department}</span>}
            {job.location && (
              <span className="inline-flex items-center gap-1">
                <MapPin className="size-3.5" aria-hidden /> {job.location}
              </span>
            )}
          </p>
        </div>
        <StatusBadge kind="job" status={job.status} />
      </div>

      <div className="mt-3 min-h-10 text-sm">
        {stats.isPending ? (
          <div className="space-y-1.5" role="status" aria-busy="true" aria-label="Loading match summary">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        ) : stats.isError || !s ? (
          <p className="text-muted-foreground">Match summary unavailable.</p>
        ) : (
          <ul className="space-y-1 text-muted-foreground">
            <li className="flex items-center gap-1.5">
              <Users className="size-3.5" aria-hidden />
              {fmt.int(s.matches_computed)} {pluralize(s.matches_computed, 'candidate')} scored ·{' '}
              {fmt.int(s.applications_total)} {pluralize(s.applications_total, 'application')}
            </li>
            <li className="flex items-center gap-1.5">
              <Clock className="size-3.5" aria-hidden />
              {s.last_matched_at ? `Last updated ${dates.relative(s.last_matched_at)}` : 'Not matched yet'}
            </li>
          </ul>
        )}
      </div>
      <p className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-primary">
        View ranking <ArrowRight className="size-4" aria-hidden />
      </p>
    </article>
  )
}

export function JobMatchCardSkeleton() {
  return (
    <div className="space-y-3 rounded-xl border bg-card p-5">
      <Skeleton className="h-5 w-1/2" />
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  )
}
