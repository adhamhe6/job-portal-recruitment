import { ChevronRight, ScrollText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState } from '@/components/common/States'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { describeAction } from '@/features/admin/lib/labels'
import type { AdminDashboardData } from '@/features/admin/api/types'
import { dates } from '@/lib/format'
import { paths } from '@/routes/paths'

export function RecentActivity({
  events,
  loading,
  error,
  onRetry,
}: {
  events: AdminDashboardData['recent_audit_events'] | undefined
  loading: boolean
  error: unknown
  onRetry: () => void
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">Recent audit events</CardTitle>
        <Link
          to={`${paths.adminSystem}?tab=audit`}
          className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          Full log <ChevronRight className="size-4" aria-hidden />
        </Link>
      </CardHeader>
      <CardContent>
        {error ? (
          <ErrorState error={error} onRetry={onRetry} compact />
        ) : loading ? (
          <div className="space-y-2" role="status" aria-busy="true" aria-label="Loading audit events">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : !events || events.length === 0 ? (
          <EmptyState compact icon={<ScrollText aria-hidden />} title="No activity recorded yet" />
        ) : (
          <ul className="divide-y" aria-label="Recent audit events">
            {events.slice(0, 8).map((e) => (
              <li key={e.id} className="flex items-start justify-between gap-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="block font-medium">{describeAction(e.action)}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {e.actor_name ?? 'System'} · {e.entity_type}
                  </span>
                </span>
                <time
                  dateTime={e.created_at}
                  title={dates.dateTime(e.created_at)}
                  className="shrink-0 text-xs text-muted-foreground"
                >
                  {dates.relative(e.created_at)}
                </time>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
