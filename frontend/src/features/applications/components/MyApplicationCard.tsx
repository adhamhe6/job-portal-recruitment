import { CalendarClock, ChevronDown, ExternalLink, Undo2 } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { MatchScoreBadge } from '@/components/common/MatchScore'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { dates } from '@/lib/format'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import type { ApplicationListItem } from '@/lib/api'
import { WITHDRAWABLE } from '../api/myApplications'
import { MyApplicationTimeline } from './MyApplicationTimeline'

export function MyApplicationCard({
  application: a,
  onWithdraw,
}: {
  application: ApplicationListItem
  onWithdraw: (a: ApplicationListItem) => void
}) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const canWithdraw = WITHDRAWABLE.includes(a.status)
  const upcoming = a.next_interview_at

  return (
    <li>
      <article
        aria-labelledby={`${panelId}-title`}
        className="rounded-xl border bg-card p-4 shadow-xs sm:p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 space-y-1">
            <h3 id={`${panelId}-title`} className="text-base font-semibold sm:text-[17px]">
              <Link to={paths.job(a.job_id)} className="rounded-sm hover:text-primary hover:underline">
                {a.job_title}
              </Link>
            </h3>
            <p className="text-sm text-muted-foreground">{a.company_name}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {a.match_score != null && <MatchScoreBadge score={a.match_score} band={a.match_band} />}
            <StatusBadge kind="application" status={a.status} />
          </div>
        </div>

        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-muted-foreground">
          <div className="flex gap-1.5">
            <dt>Applied</dt>
            <dd className="font-medium text-foreground">{dates.date(a.applied_at)}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt>Last update</dt>
            <dd className="font-medium text-foreground">{dates.relative(a.status_changed_at)}</dd>
          </div>
          {upcoming && (
            <div className="flex items-center gap-1.5">
              <CalendarClock className="size-3.5" aria-hidden />
              <dt>Next interview</dt>
              <dd className="font-medium text-foreground">
                <Link to={paths.interviews} className="hover:underline">
                  {dates.dateTime(a.next_interview_at)}
                </Link>
              </dd>
            </div>
          )}
        </dl>

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-3">
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((o) => !o)}
          >
            <ChevronDown className={cn('transition-transform', open && 'rotate-180')} />
            {open ? 'Hide history' : 'Status history'}
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to={paths.application(a.id)}>Details</Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to={paths.job(a.job_id)}>
              <ExternalLink /> View job
            </Link>
          </Button>
          {canWithdraw && (
            <Button
              variant="outline"
              size="sm"
              className="sm:ml-auto"
              onClick={() => onWithdraw(a)}
              aria-label={`Withdraw application for ${a.job_title}`}
            >
              <Undo2 /> Withdraw
            </Button>
          )}
        </div>

        <div id={panelId} hidden={!open} className="pt-4">
          {open && <MyApplicationTimeline applicationId={a.id} />}
        </div>
      </article>
    </li>
  )
}
