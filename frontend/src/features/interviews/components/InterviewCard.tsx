import { Building2, CalendarClock, Clock, ExternalLink, MapPin, Users, Video } from 'lucide-react'
import { Link } from 'react-router-dom'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { dates } from '@/lib/format'
import { paths } from '@/routes/paths'
import type { CandidateInterview } from '../api/interviews'
import {
  browserTimeZone,
  INTERVIEW_TYPE_LABELS,
  longDate,
  sameZone,
  timeOfDay,
  wallClock,
} from '../lib/format'

const CLOSED = new Set(['COMPLETED', 'CANCELLED', 'NO_SHOW'])

export function InterviewCard({
  interview: i,
  confirming,
  onConfirm,
}: {
  interview: CandidateInterview
  confirming: boolean
  onConfirm: (i: CandidateInterview) => void
}) {
  const closed = CLOSED.has(i.status)
  const sameTz = sameZone(i.timezone)
  return (
    <li>
      <article aria-labelledby={`int-${i.id}`} className="rounded-xl border bg-card p-4 shadow-xs sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 space-y-1">
            <h3 id={`int-${i.id}`} className="text-base font-semibold sm:text-[17px]">
              {INTERVIEW_TYPE_LABELS[i.interview_type] ?? i.interview_type}
              <span className="font-normal text-muted-foreground"> · {i.job_title}</span>
            </h3>
            <p className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
              <Building2 className="size-3.5" aria-hidden /> {i.company_name}
            </p>
          </div>
          <StatusBadge kind="interview" status={i.status} />
        </div>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <p className="flex items-center gap-2 font-medium">
              <CalendarClock className="size-4 text-primary" aria-hidden />
              <time dateTime={i.start_at}>{longDate(i.start_at)}</time>
            </p>
            <p className="flex items-center gap-2 text-sm">
              <Clock className="size-4 text-muted-foreground" aria-hidden />
              <span>
                <time dateTime={i.start_at}>{timeOfDay(i.start_at)}</time> –{' '}
                <time dateTime={i.end_at}>{timeOfDay(i.end_at)}</time>{' '}
                <span className="text-muted-foreground">
                  ({i.duration_minutes} min, {browserTimeZone()})
                </span>
              </span>
            </p>
            {!sameTz && (
              <p className="pl-6 text-xs text-muted-foreground">
                {wallClock(i.start_local)} – {wallClock(i.end_local)} in {i.timezone}
              </p>
            )}
            {!closed && <p className="pl-6 text-xs text-muted-foreground">{dates.relative(i.start_at)}</p>}
          </div>

          <ul className="space-y-1.5 text-sm" aria-label="Interview details">
            {i.meeting_url && (
              <li className="flex items-start gap-2">
                <Video className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                {closed ? (
                  <span className="break-all text-muted-foreground">Video call</span>
                ) : (
                  <a
                    href={i.meeting_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-medium break-all"
                  >
                    Join video call <ExternalLink className="size-3.5 shrink-0" aria-hidden />
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                )}
              </li>
            )}
            {i.location && (
              <li className="flex items-start gap-2">
                <MapPin className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="break-words">{i.location}</span>
              </li>
            )}
            {i.interviewers.length > 0 && (
              <li className="flex items-start gap-2">
                <Users className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span>
                  <span className="sr-only">Interviewers: </span>
                  {i.interviewers.join(', ')}
                </span>
              </li>
            )}
          </ul>
        </div>

        {i.status === 'RESCHEDULED' && (
          <p className="mt-3 rounded-lg bg-amber-500/10 p-2.5 text-sm text-amber-900 dark:text-amber-200">
            The time changed. Please confirm that the new slot works for you.
          </p>
        )}
        {i.status === 'CANCELLED' && (
          <p className="mt-3 rounded-lg bg-muted p-2.5 text-sm text-muted-foreground">
            This interview was cancelled. {i.company_name} will contact you if it is rescheduled.
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-3">
          {i.can_confirm && (
            <Button size="sm" onClick={() => onConfirm(i)} loading={confirming}>
              Confirm attendance
              <span className="sr-only"> for {i.job_title}</span>
            </Button>
          )}
          <Button asChild variant="ghost" size="sm">
            <Link to={paths.application(i.application_id)}>Application</Link>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to={paths.job(i.job_id)}>View job</Link>
          </Button>
          {!closed && (
            <p className="text-xs text-muted-foreground sm:ml-auto">
              Can't make it? Contact the hiring team at {i.company_name} — only they can change the schedule.
            </p>
          )}
        </div>
      </article>
    </li>
  )
}
