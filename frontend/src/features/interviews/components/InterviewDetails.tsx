import {
  CalendarCheck,
  CalendarClock,
  CalendarX2,
  CheckCircle2,
  ExternalLink,
  Info,
  Video,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Timeline, type TimelineItem } from '@/components/common/Timeline'
import { TextBlock } from '@/components/common/TextBlock'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useInterviewTransition } from '../api/staff'
import type { CandidateInterviewView, StaffInterviewView } from '../api/types'
import { describeTransitionError } from '../hooks/useInterviewActions'
import { interviewTypeLabel } from '../lib/labels'
import { formatSlot, offsetLabel, sameOffset, viewerTimeZone } from '../lib/time'
import { dates } from '@/lib/format'
import { paths } from '@/routes/paths'
import { InterviewWhere } from './InterviewParts'

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-3 sm:grid-cols-[10rem_1fr] sm:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm break-words">{children}</dd>
    </div>
  )
}

/** When: the interview's own zone (explicit), then the viewer's zone when it differs. */
export function WhenRows({
  startAt,
  endAt,
  timezone,
  durationMinutes,
}: {
  startAt: string
  endAt: string
  timezone: string
  durationMinutes: number
}) {
  const viewerTz = viewerTimeZone()
  return (
    <>
      <Row label="When">
        <p className="font-medium">{formatSlot(startAt, endAt, timezone)}</p>
        <p className="text-xs text-muted-foreground">
          {timezone.replace(/_/g, ' ')} ({offsetLabel(new Date(startAt), timezone)})
        </p>
        {!sameOffset(startAt, timezone, viewerTz) && (
          <p className="mt-1 text-xs text-muted-foreground">
            In your timezone: {formatSlot(startAt, endAt, viewerTz)}
          </p>
        )}
      </Row>
      <Row label="Duration">{durationMinutes} minutes</Row>
    </>
  )
}

export function StaffDetailsCard({ iv }: { iv: StaffInterviewView }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Details</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="divide-y">
          <WhenRows
            startAt={iv.start_at}
            endAt={iv.end_at}
            timezone={iv.timezone}
            durationMinutes={iv.duration_minutes}
          />
          <Row label="Type">{interviewTypeLabel(iv.interview_type)}</Row>
          <Row label="Where">
            <InterviewWhere location={iv.location} meetingUrl={iv.meeting_url} />
          </Row>
          <Row label="Job">
            <Link to={paths.job(iv.job_id)} className="font-medium hover:text-primary hover:underline">
              {iv.job_title}
            </Link>{' '}
            <span className="text-muted-foreground">· {iv.company_name}</span>
          </Row>
          <Row label="Candidate">
            <Link
              to={paths.candidate(iv.candidate_id)}
              className="font-medium hover:text-primary hover:underline"
            >
              {iv.candidate_name}
            </Link>
          </Row>
          <Row label="Internal notes">
            {iv.notes ? (
              <TextBlock text={iv.notes} className="text-sm" />
            ) : (
              <span className="text-muted-foreground">No notes</span>
            )}
          </Row>
          {iv.status === 'CANCELLED' && (
            <Row label="Cancellation reason">
              {iv.cancelled_reason ?? <span className="text-muted-foreground">Not recorded</span>}
            </Row>
          )}
        </dl>
      </CardContent>
    </Card>
  )
}

/**
 * Record history from the fields the API exposes. The backend writes a full audit trail but offers no read endpoint for
 * interviews to non-admin staff, so this shows creation, last change and the outcome only.
 */
export function HistoryCard({ iv }: { iv: StaffInterviewView }) {
  const items: TimelineItem[] = [
    {
      id: 'created',
      title: iv.created_by_name ? `Scheduled by ${iv.created_by_name}` : 'Scheduled',
      time: dates.dateTime(iv.created_at),
      icon: <CalendarCheck />,
    },
  ]
  if (
    iv.updated_at !== iv.created_at &&
    iv.status !== 'CANCELLED' &&
    iv.status !== 'COMPLETED' &&
    iv.status !== 'NO_SHOW'
  ) {
    items.push({
      id: 'updated',
      title: iv.status === 'RESCHEDULED' ? 'Rescheduled' : 'Last updated',
      time: dates.dateTime(iv.updated_at),
      icon: <CalendarClock />,
      tone: 'warning',
    })
  }
  if (iv.status === 'CANCELLED')
    items.push({
      id: 'cancelled',
      title: 'Cancelled',
      description: iv.cancelled_reason ? `Reason: ${iv.cancelled_reason}` : undefined,
      time: dates.dateTime(iv.updated_at),
      icon: <CalendarX2 />,
      tone: 'danger',
    })
  if (iv.status === 'COMPLETED')
    items.push({
      id: 'completed',
      title: 'Completed',
      time: dates.dateTime(iv.updated_at),
      icon: <CheckCircle2 />,
      tone: 'success',
    })
  if (iv.status === 'NO_SHOW')
    items.push({
      id: 'no-show',
      title: 'Candidate did not attend',
      time: dates.dateTime(iv.updated_at),
      icon: <CalendarX2 />,
      tone: 'danger',
    })
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">History</CardTitle>
      </CardHeader>
      <CardContent>
        <Timeline items={items} />
      </CardContent>
    </Card>
  )
}

/** The candidate's page: logistics only, plus confirming attendance. */
export function CandidateInterviewCard({ iv }: { iv: CandidateInterviewView }) {
  const confirm = useInterviewTransition()
  const notice: Partial<
    Record<
      CandidateInterviewView['status'],
      { variant: 'info' | 'success' | 'warning' | 'danger'; text: string }
    >
  > = {
    CONFIRMED: { variant: 'success', text: 'You have confirmed your attendance. See you there!' },
    RESCHEDULED: {
      variant: 'warning',
      text: 'The time of this interview changed. Please check the new time and confirm it.',
    },
    CANCELLED: {
      variant: 'danger',
      text: 'This interview was cancelled. The hiring team will be in touch if a new time is needed.',
    },
    COMPLETED: {
      variant: 'info',
      text: 'This interview has taken place. The team will update you on the next steps.',
    },
    NO_SHOW: {
      variant: 'warning',
      text: 'This interview was recorded as missed. Contact the hiring team if that is a mistake.',
    },
  }
  const n = notice[iv.status]
  return (
    <div className="space-y-5">
      {n && <Alert variant={n.variant}>{n.text}</Alert>}
      {confirm.isError && <Alert variant="danger">{describeTransitionError(confirm.error)}</Alert>}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Interview details</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="divide-y">
            <WhenRows
              startAt={iv.start_at}
              endAt={iv.end_at}
              timezone={iv.timezone}
              durationMinutes={iv.duration_minutes}
            />
            <Row label="Type">{interviewTypeLabel(iv.interview_type)}</Row>
            <Row label="Where">
              {iv.location || iv.meeting_url ? (
                <InterviewWhere location={iv.location} meetingUrl={iv.meeting_url} />
              ) : (
                <span className="text-muted-foreground">Details will follow</span>
              )}
            </Row>
            <Row label="Company">{iv.company_name}</Row>
            <Row label="Role">
              <Link to={paths.job(iv.job_id)} className="font-medium hover:text-primary hover:underline">
                {iv.job_title}
              </Link>
            </Row>
            <Row label="You will meet">
              {iv.interviewers.length ? (
                iv.interviewers.join(', ')
              ) : (
                <span className="text-muted-foreground">To be confirmed</span>
              )}
            </Row>
          </dl>
        </CardContent>
      </Card>
      <div className="flex flex-wrap items-center gap-3">
        {iv.can_confirm && (
          <Button
            loading={confirm.isPending}
            onClick={() => confirm.mutate({ id: iv.id, action: 'confirm' })}
          >
            <CheckCircle2 /> Confirm attendance
          </Button>
        )}
        {iv.meeting_url && iv.status !== 'CANCELLED' && (
          <Button asChild variant="outline">
            <a href={iv.meeting_url} target="_blank" rel="noopener noreferrer">
              <Video /> Open meeting link <ExternalLink className="size-3.5" aria-hidden />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          </Button>
        )}
        <Button asChild variant="ghost">
          <Link to={paths.application(iv.application_id)}>View my application</Link>
        </Button>
      </div>
      <p className="flex items-start gap-2 text-xs text-muted-foreground">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Times are shown in the interview&apos;s timezone and in yours.
      </p>
    </div>
  )
}
