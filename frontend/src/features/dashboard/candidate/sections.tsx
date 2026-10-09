import { ArrowRight, CalendarClock, CheckCircle2, Circle, FileText, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState } from '@/components/common/States'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { useMyInterviews } from '@/features/interviews/api/myInterviews'
import { INTERVIEW_TYPE_LABELS, longDate, timeOfDay } from '@/features/interviews/lib/myInterviewFormat'
import { JobCard, JobCardSkeleton } from '@/features/jobs/components/JobCard'
import { NotificationItem } from '@/features/notifications/components/NotificationItem'
import { useMarkRead, useNotifications } from '@/features/notifications/api/notifications'
import { COMPLETION_TARGETS } from '@/features/profile/components/CompletionCard'
import { useProfileCompletion } from '@/features/profile/api/profile'
import { useRecommendations } from '@/features/recommendations/api/recommendations'
import { useMyResumes } from '@/features/resumes/api/resumes'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { countByStatus, STATUS_ORDER, useDashboardApplications } from './api'

function Panel({
  title,
  description,
  action,
  icon,
  children,
  className,
}: {
  title: string
  description?: string
  action?: ReactNode
  icon?: ReactNode
  children: ReactNode
  className?: string
}) {
  const id = `panel-${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
  return (
    <Card aria-labelledby={id} className={cn('flex flex-col', className)}>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle
            id={id}
            className="flex items-center gap-2 text-base [&_svg]:size-4 [&_svg]:text-primary"
          >
            {icon}
            {title}
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        {action}
      </CardHeader>
      <CardContent className="flex-1">{children}</CardContent>
    </Card>
  )
}

const RowsSkeleton = ({ rows = 3, label }: { rows?: number; label: string }) => (
  <div className="space-y-3" role="status" aria-busy="true" aria-label={label}>
    {Array.from({ length: rows }, (_, i) => (
      <Skeleton key={i} className="h-10 w-full" />
    ))}
  </div>
)

// --- applications by status --------------------------------------------------------------------------------------------

export function ApplicationsByStatus() {
  const q = useDashboardApplications()
  const action = (
    <Button asChild variant="ghost" size="sm">
      <Link to={paths.applications}>
        View all <ArrowRight />
      </Link>
    </Button>
  )
  return (
    <Panel
      title="Applications by status"
      description="Where each of your applications stands."
      action={action}
    >
      {q.isPending ? (
        <RowsSkeleton rows={4} label="Loading applications" />
      ) : q.isError ? (
        <ErrorState compact error={q.error} onRetry={() => q.refetch()} title="Couldn't load applications" />
      ) : q.data.total === 0 ? (
        <EmptyState
          compact
          title="No applications yet"
          description="Apply to a job and its progress will be tracked here."
          action={
            <Button asChild size="sm">
              <Link to={paths.jobs}>Browse jobs</Link>
            </Button>
          }
        />
      ) : (
        <StatusBars items={q.data.items} total={q.data.total} />
      )}
    </Panel>
  )
}

function StatusBars({ items, total }: { items: Parameters<typeof countByStatus>[0]; total: number }) {
  const counts = countByStatus(items)
  const max = Math.max(1, ...Object.values(counts))
  return (
    <div>
      <ul className="grid gap-2.5" aria-label="Applications by status">
        {STATUS_ORDER.filter((s) => counts[s] > 0 || ['APPLIED', 'INTERVIEW', 'OFFER'].includes(s)).map(
          (s) => (
            <li key={s} className="grid grid-cols-[6.5rem_1fr_2rem] items-center gap-3 text-sm">
              <Link
                to={`${paths.applications}?status=${s}`}
                className="truncate rounded-sm hover:text-primary hover:underline"
              >
                {APPLICATION_STATUS_LABELS[s]}
              </Link>
              <div className="h-2.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                <div
                  className="h-full rounded-full bg-[var(--chart-1)]"
                  style={{ width: `${(counts[s] / max) * 100}%` }}
                />
              </div>
              <span className="text-right font-semibold tabular">{counts[s]}</span>
            </li>
          ),
        )}
      </ul>
      {total > items.length && (
        <p className="mt-3 text-xs text-muted-foreground">
          Based on your {items.length} most recently updated of {total} applications.
        </p>
      )}
    </div>
  )
}

// --- upcoming interviews -----------------------------------------------------------------------------------------------

export function UpcomingInterviews() {
  const q = useMyInterviews({ view: 'upcoming', page: 1, pageSize: 3 })
  return (
    <Panel
      title="Upcoming interviews"
      icon={<CalendarClock aria-hidden />}
      action={
        <Button asChild variant="ghost" size="sm">
          <Link to={paths.interviews}>
            All interviews <ArrowRight />
          </Link>
        </Button>
      }
    >
      {q.isPending ? (
        <RowsSkeleton label="Loading interviews" />
      ) : q.isError ? (
        <ErrorState compact error={q.error} onRetry={() => q.refetch()} title="Couldn't load interviews" />
      ) : q.data.items.length === 0 ? (
        <EmptyState
          compact
          icon={<CalendarClock aria-hidden />}
          title="No interviews scheduled"
          description="When a hiring team invites you, the date and time will show up here."
        />
      ) : (
        <ul className="divide-y" aria-label="Upcoming interviews">
          {q.data.items.map((i) => (
            <li
              key={i.id}
              className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0"
            >
              <div className="min-w-0">
                <p className="truncate font-medium">{i.job_title}</p>
                <p className="text-sm text-muted-foreground">
                  {i.company_name} · {INTERVIEW_TYPE_LABELS[i.interview_type]}
                </p>
                <p className="mt-0.5 text-sm">
                  <time dateTime={i.start_at}>
                    {longDate(i.start_at)}, {timeOfDay(i.start_at)}
                  </time>
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge kind="interview" status={i.status} />
                {i.can_confirm && (
                  <Button asChild size="sm" variant="outline">
                    <Link to={paths.interviews}>Confirm</Link>
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

// --- recommended jobs ------------------------------------------------------------------------------------------------

export function TopRecommendations() {
  const q = useRecommendations({
    minScore: 0,
    workplace: [],
    employment: [],
    location: '',
    skillIds: [],
    sort: 'score',
    page: 1,
    pageSize: 3,
  })
  return (
    <Panel
      title="Top recommended jobs"
      icon={<Sparkles aria-hidden />}
      description="Open roles that fit your profile best."
      action={
        <Button asChild variant="ghost" size="sm">
          <Link to={paths.recommended}>
            See all <ArrowRight />
          </Link>
        </Button>
      }
    >
      {q.isPending ? (
        <div className="space-y-3" role="status" aria-busy="true" aria-label="Loading recommendations">
          <JobCardSkeleton />
          <JobCardSkeleton />
        </div>
      ) : q.isError && !q.data ? (
        <ErrorState
          compact
          error={q.error}
          onRetry={() => q.refetch()}
          title="Couldn't load recommendations"
        />
      ) : q.data && q.data.items.length === 0 ? (
        <EmptyState
          compact
          icon={<Sparkles aria-hidden />}
          title="No recommendations yet"
          description={
            q.data.meta.hint ?? 'Add skills to your profile or upload a résumé to get ranked suggestions.'
          }
          action={
            <Button asChild size="sm">
              <Link to={paths.profile}>Complete profile</Link>
            </Button>
          }
        />
      ) : q.data ? (
        <ul className="space-y-3" aria-label="Top recommended jobs">
          {q.data.items.map(({ job, match }) => (
            <li key={job.id}>
              <JobCard job={job} matchPercent={match.overall_percent} matchBand={match.band} />
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  )
}

// --- profile + résumé prompts --------------------------------------------------------------------------------------------

export function ProfileProgress() {
  const completion = useProfileCompletion()
  const resumes = useMyResumes()
  const processing = resumes.data?.some((r) => r.status === 'UPLOADED' || r.status === 'PROCESSING')
  const hasProcessed = resumes.data?.some((r) => r.status === 'PROCESSED')
  return (
    <Panel
      title="Profile completeness"
      description="A complete profile ranks higher in matches."
      action={
        <Button asChild variant="ghost" size="sm">
          <Link to={paths.profile}>
            Edit <ArrowRight />
          </Link>
        </Button>
      }
    >
      {completion.isPending ? (
        <RowsSkeleton label="Loading profile completeness" />
      ) : completion.isError ? (
        <ErrorState
          compact
          error={completion.error}
          onRetry={() => completion.refetch()}
          title="Couldn't load your profile"
        />
      ) : (
        <div className="grid gap-4">
          <div className="space-y-2">
            <p className="text-3xl font-semibold tabular">{completion.data.percent}%</p>
            <Progress value={completion.data.percent} label="Profile completeness" />
          </div>
          {completion.data.items.some((i) => !i.done) ? (
            <ul className="grid gap-1.5 text-sm" aria-label="Next steps">
              {completion.data.items
                .filter((i) => !i.done)
                .map((i) => {
                  const target = COMPLETION_TARGETS[i.key]
                  const to = target?.startsWith('#') ? `${paths.profile}${target}` : (target ?? paths.profile)
                  return (
                    <li key={i.key}>
                      <Link to={to} className="flex items-center gap-2 rounded-sm hover:text-primary">
                        <Circle className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                        {i.label}
                        <span className="ml-auto text-xs text-muted-foreground">+{i.weight}%</span>
                      </Link>
                    </li>
                  )
                })}
            </ul>
          ) : (
            <p className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 className="size-4" aria-hidden /> Your profile is complete.
            </p>
          )}
          {processing ? (
            <p role="status" className="flex items-center gap-2 rounded-lg bg-surface p-3 text-sm">
              <FileText className="size-4 text-primary" aria-hidden /> Your résumé is being processed…
            </p>
          ) : hasProcessed ? (
            <p className="rounded-lg bg-surface p-3 text-sm">
              <FileText className="mr-2 inline size-4 text-primary" aria-hidden />
              Review the skills and experience we found in your résumé.{' '}
              <Link to={paths.resume} className="font-medium">
                Review suggestions
              </Link>
            </p>
          ) : null}
        </div>
      )}
    </Panel>
  )
}

// --- notifications ---------------------------------------------------------------------------------------------------

export function RecentNotifications() {
  const q = useNotifications({ pageSize: 5 })
  const markRead = useMarkRead()
  return (
    <Panel
      title="Recent notifications"
      action={
        <Button asChild variant="ghost" size="sm">
          <Link to={paths.notifications}>
            All <ArrowRight />
          </Link>
        </Button>
      }
    >
      {q.isPending ? (
        <RowsSkeleton rows={4} label="Loading notifications" />
      ) : q.isError ? (
        <ErrorState compact error={q.error} onRetry={() => q.refetch()} title="Couldn't load notifications" />
      ) : q.data.items.length === 0 ? (
        <EmptyState
          compact
          title="You're all caught up"
          description="Updates about your applications and interviews appear here."
        />
      ) : (
        <ul className="-mx-5 divide-y" aria-label="Recent notifications">
          {q.data.items.map((n) => (
            <li key={n.id}>
              <NotificationItem
                notification={n}
                dense
                onOpen={(item) => {
                  if (!item.is_read) markRead.mutate(item.id)
                }}
              />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

// --- KPI strip -------------------------------------------------------------------------------------------------------

export function useDashboardKpis() {
  const apps = useDashboardApplications()
  const interviews = useMyInterviews({ view: 'upcoming', page: 1, pageSize: 3 })
  const completion = useProfileCompletion()
  const active = apps.data
    ? apps.data.items.filter((a) => !['HIRED', 'REJECTED', 'WITHDRAWN'].includes(a.status)).length
    : undefined
  const offers = apps.data ? apps.data.items.filter((a) => a.status === 'OFFER').length : undefined
  return { apps, interviews, completion, active, offers }
}
