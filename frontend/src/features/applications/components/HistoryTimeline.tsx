import { ArrowRight, CircleCheck, CircleX, Send, Undo2 } from 'lucide-react'
import { Timeline, type TimelineItem } from '@/components/common/Timeline'
import type { ApplicationStatus, components } from '@/lib/api'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { dates } from '@/lib/format'

type Entry = components['schemas']['HistoryEntry']

const ICON: Partial<Record<ApplicationStatus, React.ReactNode>> = {
  APPLIED: <Send aria-hidden />,
  HIRED: <CircleCheck aria-hidden />,
  REJECTED: <CircleX aria-hidden />,
  WITHDRAWN: <Undo2 aria-hidden />,
}
const TONE: Partial<Record<ApplicationStatus, TimelineItem['tone']>> = {
  HIRED: 'success',
  OFFER: 'success',
  REJECTED: 'danger',
  WITHDRAWN: 'muted',
  INTERVIEW: 'warning',
}

/** Audited status history, newest first. The API already redacts actors/comments for candidates. */
export function HistoryTimeline({ history }: { history: Entry[] }) {
  const items: TimelineItem[] = [...history]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map((h) => ({
      id: h.id,
      title: h.from_status ? (
        <span className="inline-flex flex-wrap items-center gap-1">
          {APPLICATION_STATUS_LABELS[h.from_status]} <ArrowRight className="size-3.5" aria-label="to" />{' '}
          {APPLICATION_STATUS_LABELS[h.to_status]}
        </span>
      ) : (
        'Application submitted'
      ),
      description: (
        <>
          {h.actor_name && <span>By {h.actor_name}</span>}
          {h.comment && <span className="mt-0.5 block text-foreground/80">“{h.comment}”</span>}
        </>
      ),
      time: (
        <time dateTime={h.created_at} title={dates.dateTime(h.created_at)}>
          {dates.relative(h.created_at)}
        </time>
      ),
      icon: ICON[h.to_status] ?? undefined,
      tone: TONE[h.to_status] ?? 'default',
    }))
  return <Timeline items={items} />
}
