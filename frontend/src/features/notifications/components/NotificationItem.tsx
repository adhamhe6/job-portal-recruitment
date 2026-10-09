import {
  Bell,
  BriefcaseBusiness,
  CalendarClock,
  FileCheck2,
  FileWarning,
  Sparkles,
  Target,
  UserPlus,
  Users,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { dates } from '@/lib/format'
import type { NotificationOut, NotificationType } from '@/lib/api'
import { cn } from '@/lib/utils'
import { notificationHref } from '../lib/links'

const ICONS: Record<NotificationType, { icon: ReactNode; tone: string }> = {
  APPLICATION_SUBMITTED: { icon: <UserPlus />, tone: 'bg-sky-500/12 text-sky-700 dark:text-sky-300' },
  APPLICATION_STATUS_CHANGED: {
    icon: <BriefcaseBusiness />,
    tone: 'bg-violet-500/12 text-violet-700 dark:text-violet-300',
  },
  INTERVIEW_SCHEDULED: {
    icon: <CalendarClock />,
    tone: 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-300',
  },
  INTERVIEW_RESCHEDULED: {
    icon: <CalendarClock />,
    tone: 'bg-amber-500/15 text-amber-800 dark:text-amber-300',
  },
  INTERVIEW_CANCELLED: { icon: <CalendarClock />, tone: 'bg-red-500/12 text-red-700 dark:text-red-300' },
  RESUME_PROCESSED: {
    icon: <FileCheck2 />,
    tone: 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-300',
  },
  RESUME_FAILED: { icon: <FileWarning />, tone: 'bg-red-500/12 text-red-700 dark:text-red-300' },
  NEW_CANDIDATE_MATCH: { icon: <Target />, tone: 'bg-primary-soft text-primary-soft-foreground' },
  NEW_JOB_RECOMMENDATION: { icon: <Sparkles />, tone: 'bg-primary-soft text-primary-soft-foreground' },
  BULK_IMPORT_COMPLETED: { icon: <Users />, tone: 'bg-sky-500/12 text-sky-700 dark:text-sky-300' },
}

export function NotificationIcon({ type, className }: { type: NotificationType; className?: string }) {
  const def = ICONS[type] ?? { icon: <Bell />, tone: 'bg-muted text-muted-foreground' }
  return (
    <span
      className={cn(
        'flex size-9 shrink-0 items-center justify-center rounded-full [&_svg]:size-4.5',
        def.tone,
        className,
      )}
      aria-hidden
    >
      {def.icon}
    </span>
  )
}

/**
 * One notification row. Clicking marks it read and follows its deep link (job / application / interview / résumé).
 * Rows without a target render as plain, still markable rows.
 */
export function NotificationItem({
  notification: n,
  onOpen,
  dense,
}: {
  notification: NotificationOut
  /** Called when the row is activated (mark read + close popover). */
  onOpen: (n: NotificationOut) => void
  dense?: boolean
}) {
  const href = notificationHref(n)
  const body = (
    <>
      <NotificationIcon type={n.type} />
      <span className="min-w-0 flex-1">
        <span className="flex items-start justify-between gap-2">
          <span className={cn('block text-sm', n.is_read ? 'font-medium' : 'font-semibold')}>{n.title}</span>
          {!n.is_read && (
            <>
              <span className="mt-1.5 size-2 shrink-0 rounded-full bg-primary" aria-hidden />
              <span className="sr-only">Unread</span>
            </>
          )}
        </span>
        <span className={cn('mt-0.5 block text-sm text-muted-foreground', dense && 'line-clamp-2')}>
          {n.message}
        </span>
        <time dateTime={n.created_at} className="mt-1 block text-xs text-muted-foreground">
          {dates.relative(n.created_at)}
        </time>
      </span>
    </>
  )
  const cls = cn(
    'flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/60 focus-visible:bg-accent/60',
    !n.is_read && 'bg-primary-soft/40',
  )
  return href ? (
    <Link to={href} onClick={() => onOpen(n)} className={cls}>
      {body}
    </Link>
  ) : (
    <button type="button" onClick={() => onOpen(n)} className={cn(cls, 'cursor-pointer')}>
      {body}
    </button>
  )
}
