import { ArrowRight, Ban, CheckCircle2, CircleDot, Undo2 } from 'lucide-react'
import { ErrorState } from '@/components/common/States'
import { Timeline, type TimelineItem } from '@/components/common/Timeline'
import { Skeleton } from '@/components/ui/skeleton'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { dates } from '@/lib/format'
import { useApplicationHistory, type HistoryEntry } from '../api/myApplications'

function toItem(h: HistoryEntry): TimelineItem {
  const to = APPLICATION_STATUS_LABELS[h.to_status] ?? h.to_status
  const tone: TimelineItem['tone'] =
    h.to_status === 'REJECTED'
      ? 'danger'
      : h.to_status === 'HIRED' || h.to_status === 'OFFER'
        ? 'success'
        : h.to_status === 'WITHDRAWN'
          ? 'muted'
          : 'default'
  const icon =
    h.to_status === 'REJECTED' ? (
      <Ban />
    ) : h.to_status === 'WITHDRAWN' ? (
      <Undo2 />
    ) : h.to_status === 'HIRED' ? (
      <CheckCircle2 />
    ) : h.from_status ? (
      <ArrowRight />
    ) : (
      <CircleDot />
    )
  return {
    id: h.id,
    title: h.from_status ? `Moved to ${to}` : 'Application submitted',
    description:
      [h.comment, h.actor_name ? `by ${h.actor_name}` : null].filter(Boolean).join(' · ') || undefined,
    time: <time dateTime={h.created_at}>{dates.dateTime(h.created_at)}</time>,
    tone,
    icon,
  }
}

/** Newest-first history of an application's status changes. */
export function MyApplicationTimeline({ applicationId }: { applicationId: string }) {
  const q = useApplicationHistory(applicationId, true)
  if (q.isPending)
    return (
      <div className="space-y-3" role="status" aria-busy="true" aria-label="Loading history">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-10 w-1/2" />
      </div>
    )
  if (q.isError)
    return (
      <ErrorState compact error={q.error} onRetry={() => q.refetch()} title="Couldn't load the history" />
    )
  const items = [...q.data].sort((a, b) => b.created_at.localeCompare(a.created_at)).map(toItem)
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No status changes yet.</p>
  return <Timeline items={items} />
}
