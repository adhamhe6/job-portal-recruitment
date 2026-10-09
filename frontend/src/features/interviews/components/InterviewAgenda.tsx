import { MessageSquareText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Card } from '@/components/ui/card'
import { pluralize } from '@/lib/utils'
import { paths } from '@/routes/paths'
import type { StaffInterviewItem } from '../api/types'
import type { InterviewAction } from '../hooks/useInterviewActions'
import type { AgendaDay } from '../lib/agenda'
import { interviewTypeLabel } from '../lib/labels'
import { InterviewRowActions } from './InterviewRowActions'
import { InterviewTime, InterviewWhere, ParticipantNames } from './InterviewParts'

/** One interview as a row/card: time, who, what, where, status and the actions menu. */
export function InterviewCard({
  interview: iv,
  viewerTz,
  onAction,
}: {
  interview: StaffInterviewItem
  viewerTz: string
  onAction: (interview: StaffInterviewItem, action: InterviewAction) => void
}) {
  const dimmed = iv.status === 'CANCELLED' || iv.status === 'NO_SHOW'
  return (
    <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:gap-5">
      <InterviewTime
        startAt={iv.start_at}
        endAt={iv.end_at}
        timezone={iv.timezone}
        viewerTz={viewerTz}
        className="text-sm sm:w-48 sm:shrink-0"
      />
      <div className={dimmed ? 'min-w-0 flex-1 space-y-1.5 opacity-75' : 'min-w-0 flex-1 space-y-1.5'}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Link
            to={paths.interview(iv.id)}
            className="rounded-sm font-medium hover:text-primary hover:underline"
          >
            {iv.candidate_name}
            <span className="sr-only">, {interviewTypeLabel(iv.interview_type)}</span>
          </Link>
          <StatusBadge kind="interview" status={iv.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          {interviewTypeLabel(iv.interview_type)} · {iv.job_title}
        </p>
        <ParticipantNames participants={iv.participants} />
        <InterviewWhere location={iv.location} meetingUrl={iv.meeting_url} />
      </div>
      <div className="flex items-center gap-2 sm:flex-col sm:items-end">
        {iv.feedback_count > 0 && (
          <span
            className="inline-flex items-center gap-1 text-xs text-muted-foreground"
            title="Feedback entries submitted"
          >
            <MessageSquareText className="size-3.5" aria-hidden />
            {pluralize(iv.feedback_count, 'feedback entry', 'feedback entries')}
          </span>
        )}
        <InterviewRowActions interview={iv} onAction={onAction} />
      </div>
    </div>
  )
}

/** Day-grouped agenda ("calendar view"): one heading per day, interviews ordered as returned by the API. */
export function InterviewAgenda({
  days,
  viewerTz,
  onAction,
  busy,
}: {
  days: AgendaDay[]
  viewerTz: string
  onAction: (interview: StaffInterviewItem, action: InterviewAction) => void
  busy?: boolean
}) {
  return (
    <div
      className={busy ? 'space-y-6 opacity-60 transition-opacity' : 'space-y-6'}
      aria-busy={busy || undefined}
    >
      {days.map((day) => (
        <section key={day.key} aria-labelledby={`day-${day.key}`}>
          <h2
            id={`day-${day.key}`}
            className="mb-2 text-sm font-semibold tracking-tight text-muted-foreground"
          >
            {day.heading}
            <span className="ml-2 font-normal">({pluralize(day.items.length, 'interview')})</span>
          </h2>
          <Card className="overflow-hidden">
            <ul className="divide-y">
              {day.items.map((iv) => (
                <li key={iv.id}>
                  <InterviewCard interview={iv} viewerTz={viewerTz} onAction={onAction} />
                </li>
              ))}
            </ul>
          </Card>
        </section>
      ))}
    </div>
  )
}
