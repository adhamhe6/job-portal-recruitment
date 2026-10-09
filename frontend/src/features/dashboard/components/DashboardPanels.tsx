import { CalendarClock, Funnel, Trophy, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { MatchScoreBadge } from '@/components/common/MatchScore'
import { EmptyState, ErrorState } from '@/components/common/States'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { dates, fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import type { RecruiterDashboardData, UpcomingInterview } from '../api/dashboard'
import type { Paginated } from '@/lib/api'

type Q<T> = {
  data: T | undefined
  isPending: boolean
  isError: boolean
  error: unknown
  refetch: () => unknown
}

function ListSkeleton({ rows = 4, label }: { rows?: number; label: string }) {
  return (
    <div className="space-y-3" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  )
}

function Panel({
  title,
  description,
  icon,
  action,
  children,
}: {
  title: string
  description?: string
  icon: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="grid gap-1">
          <CardTitle className="flex items-center gap-2 text-base [&_svg]:size-4 [&_svg]:text-primary">
            {icon} {title}
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        {action}
      </CardHeader>
      <CardContent className="flex-1">{children}</CardContent>
    </Card>
  )
}

/** Conversion funnel: applications that ever reached each stage, with stage-to-stage conversion. */
export function FunnelPanel({ query }: { query: Q<RecruiterDashboardData> }) {
  const main = query.data?.funnel.filter((f) => !f.is_branch) ?? []
  const branches = query.data?.funnel.filter((f) => f.is_branch) ?? []
  const top = main[0]?.count ?? 0
  return (
    <Panel
      title="Hiring funnel"
      description="Applications that reached each stage in this period"
      icon={<Funnel aria-hidden />}
    >
      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} compact />
      ) : query.isPending ? (
        <ListSkeleton label="Loading funnel" rows={6} />
      ) : top === 0 ? (
        <EmptyState
          compact
          title="No applications in this period"
          description="The funnel fills in as candidates apply."
        />
      ) : (
        <>
          <ol className="space-y-2.5" aria-label="Funnel stages">
            {main.map((f) => (
              <li key={f.stage}>
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium">{APPLICATION_STATUS_LABELS[f.stage]}</span>
                  <span className="text-muted-foreground tabular">
                    <span className="font-semibold text-foreground">{fmt.int(f.count)}</span>
                    {f.pct_of_previous != null && ` · ${fmt.num(f.pct_of_previous)}% of previous`}
                  </span>
                </div>
                <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <div
                    className="h-full rounded-full bg-[var(--chart-1)]"
                    style={{ width: `${top ? Math.max(2, (f.count / top) * 100) : 0}%` }}
                  />
                </div>
              </li>
            ))}
          </ol>
          {branches.length > 0 && (
            <p className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
              {branches.map((b) => (
                <span key={b.stage}>
                  {APPLICATION_STATUS_LABELS[b.stage]}:{' '}
                  <span className="font-semibold text-foreground">{fmt.int(b.count)}</span>
                </span>
              ))}
            </p>
          )}
        </>
      )}
    </Panel>
  )
}

/** Jobs with the most applicants in the period; each row links to that job's pipeline. */
export function TopJobsPanel({ query }: { query: Q<RecruiterDashboardData> }) {
  const jobs = query.data?.applications_by_job ?? []
  const max = Math.max(1, ...jobs.map((j) => j.applications))
  return (
    <Panel
      title="Top jobs by applicants"
      description="Most applications received in this period"
      icon={<Trophy aria-hidden />}
    >
      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} compact />
      ) : query.isPending ? (
        <ListSkeleton label="Loading top jobs" />
      ) : jobs.length === 0 ? (
        <EmptyState
          compact
          title="No applicants yet"
          description="Publish a job to start receiving applications."
          action={
            <Button asChild variant="outline" size="sm">
              <Link to={paths.manageJobs}>Manage jobs</Link>
            </Button>
          }
        />
      ) : (
        <ol className="space-y-3" aria-label="Top jobs">
          {jobs.slice(0, 6).map((j) => (
            <li key={j.job_id}>
              <Link
                to={`${paths.applications}?job_id=${j.job_id}`}
                className="group block rounded-md"
                aria-label={`${j.title}: ${j.applications} applications`}
              >
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="truncate font-medium group-hover:text-primary group-hover:underline">
                    {j.title}
                  </span>
                  <span className="font-semibold tabular">{fmt.int(j.applications)}</span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <div
                    className="h-full rounded-full bg-[var(--chart-2)]"
                    style={{ width: `${(j.applications / max) * 100}%` }}
                  />
                </div>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  )
}

export function UpcomingInterviewsPanel({ query }: { query: Q<Paginated<UpcomingInterview>> }) {
  const items = query.data?.items ?? []
  return (
    <Panel
      title="Upcoming interviews"
      description="Next scheduled interviews"
      icon={<CalendarClock aria-hidden />}
      action={
        <Button asChild variant="ghost" size="sm">
          <Link to={paths.interviews}>View all</Link>
        </Button>
      }
    >
      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} compact />
      ) : query.isPending ? (
        <ListSkeleton label="Loading interviews" rows={3} />
      ) : items.length === 0 ? (
        <EmptyState
          compact
          icon={<CalendarClock aria-hidden />}
          title="No upcoming interviews"
          description="Shortlisted candidates can be scheduled from their application."
        />
      ) : (
        <ul className="divide-y" aria-label="Upcoming interviews">
          {items.map((i) => (
            <li key={i.id} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1">
                <Link
                  to={paths.interview(i.id)}
                  className="block truncate rounded-sm text-sm font-medium hover:text-primary hover:underline"
                >
                  {i.candidate_name}
                </Link>
                <p className="truncate text-xs text-muted-foreground">
                  {i.job_title} · {fmt.label(i.interview_type)}
                </p>
              </div>
              <div className="shrink-0 text-right text-xs">
                <time dateTime={i.start_at} className="block font-medium">
                  {dates.dateTime(i.start_at)}
                </time>
                <StatusBadge kind="interview" status={i.status} className="mt-1" />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

/** Latest applications plus the best open matches, both linking into the application pipeline. */
export function RecentActivityPanel({ query }: { query: Q<RecruiterDashboardData> }) {
  const items = query.data?.recent_applications ?? []
  return (
    <Panel
      title="Recent applications"
      description="The latest candidates to apply"
      icon={<Users aria-hidden />}
      action={
        <Button asChild variant="ghost" size="sm">
          <Link to={paths.applications}>View all</Link>
        </Button>
      }
    >
      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} compact />
      ) : query.isPending ? (
        <ListSkeleton label="Loading recent applications" />
      ) : items.length === 0 ? (
        <EmptyState compact title="No applications yet" description="New applications will show up here." />
      ) : (
        <ul className="divide-y" aria-label="Recent applications">
          {items.map((a) => (
            <li key={a.id} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1">
                <Link
                  to={paths.application(a.id)}
                  className="block truncate rounded-sm text-sm font-medium hover:text-primary hover:underline"
                >
                  {a.candidate_name}
                </Link>
                <p className="truncate text-xs text-muted-foreground">
                  {a.job_title} · {dates.relative(a.applied_at)}
                </p>
              </div>
              <MatchScoreBadge score={a.match_score} band={a.match_band} />
              <StatusBadge kind="application" status={a.status} className="max-sm:hidden" />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
