import { CalendarClock, ExternalLink, MapPin } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router-dom'
import { StatusBadge } from '@/components/common/StatusBadge'
import { EmptyState, ErrorState } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { ApplicationStatus } from '@/lib/api'
import { dates, fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import { useApplicationInterviews } from '../api/applications'
import { canScheduleInterview } from '../lib/workflow'

// Owned by the interviews module; loaded only when the dialog is opened.
const ScheduleInterviewDialog = lazy(() =>
  import('@/features/interviews/components/ScheduleInterviewDialog').then((m) => ({
    default: m.ScheduleInterviewDialog,
  })),
)

/**
 * Interviews of this application plus the "Schedule interview" entry point (the interviews module's dialog).
 */
export function ApplicationInterviews({
  applicationId,
  status,
}: {
  applicationId: string
  status: ApplicationStatus
}) {
  const { can } = useAuth()
  const [scheduling, setScheduling] = useState(false)
  const query = useApplicationInterviews(applicationId, true)
  const canSchedule = can('schedule_interviews')
  const schedulable = canScheduleInterview(status)

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="grid gap-1">
          <CardTitle className="flex items-center gap-2 text-base">
            <CalendarClock className="size-4 text-primary" aria-hidden /> Interviews
          </CardTitle>
          <CardDescription>
            {canSchedule && !schedulable
              ? 'Interviews can be scheduled once the application is shortlisted.'
              : 'Scheduled and past interviews for this application.'}
          </CardDescription>
        </div>
        {canSchedule && schedulable && (
          <Button size="sm" onClick={() => setScheduling(true)}>
            Schedule interview
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {query.isPending ? (
          <div className="space-y-2" role="status" aria-label="Loading interviews">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : query.isError ? (
          <ErrorState
            error={query.error}
            onRetry={() => query.refetch()}
            compact
            title="Couldn't load interviews"
          />
        ) : query.data.items.length === 0 ? (
          <EmptyState
            compact
            title="No interviews yet"
            description="Scheduled interviews will be listed here."
          />
        ) : (
          <ul className="divide-y rounded-lg border" aria-label="Interviews">
            {query.data.items.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
                <div className="min-w-0 flex-1">
                  <Link
                    to={paths.interview(i.id)}
                    className="rounded-sm text-sm font-medium hover:text-primary hover:underline"
                  >
                    {fmt.label(i.interview_type)}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    <time dateTime={i.start_at}>{dates.dateTime(i.start_at)}</time>
                    {i.timezone ? ` · ${i.timezone}` : ''}
                  </p>
                  {(i.location || i.meeting_url) && (
                    <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                      {i.meeting_url ? (
                        <ExternalLink className="size-3" aria-hidden />
                      ) : (
                        <MapPin className="size-3" aria-hidden />
                      )}
                      {i.location ?? 'Video meeting'}
                    </p>
                  )}
                </div>
                <StatusBadge kind="interview" status={i.status} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      {scheduling && (
        <Suspense fallback={null}>
          <ScheduleInterviewDialog
            applicationId={applicationId}
            open={scheduling}
            onOpenChange={setScheduling}
          />
        </Suspense>
      )}
    </Card>
  )
}
