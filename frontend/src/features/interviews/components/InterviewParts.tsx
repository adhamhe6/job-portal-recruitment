import { ExternalLink, MapPin, Users, Video } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import type { ParticipantOut } from '../api/types'
import { formatClockRange, sameOffset } from '../lib/time'

/** Time of an interview in the viewer's zone, plus the interview's own zone when it differs. Zones are always named. */
export function InterviewTime({
  startAt,
  endAt,
  timezone,
  viewerTz,
  className,
}: {
  startAt: string
  endAt: string
  timezone: string
  viewerTz: string
  className?: string
}) {
  const differs = !sameOffset(startAt, timezone, viewerTz)
  return (
    <div className={cn('tabular', className)}>
      <p className="font-medium whitespace-nowrap">{formatClockRange(startAt, endAt, viewerTz)}</p>
      {differs && (
        <p className="text-xs text-muted-foreground">
          {formatClockRange(startAt, endAt, timezone)} in {timezone.replace(/_/g, ' ')}
        </p>
      )}
    </div>
  )
}

/** "Room 3, HQ" and/or a join link. */
export function InterviewWhere({
  location,
  meetingUrl,
  className,
}: {
  location: string | null
  meetingUrl: string | null
  className?: string
}) {
  if (!location && !meetingUrl) return <span className="text-muted-foreground">—</span>
  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 text-sm', className)}>
      {location && (
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <MapPin className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <span className="break-words">{location}</span>
        </span>
      )}
      {meetingUrl && (
        <a
          href={meetingUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-sm font-medium text-primary hover:underline"
        >
          <Video className="size-3.5" aria-hidden />
          Join link
          <ExternalLink className="size-3" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      )}
    </div>
  )
}

/** Participant names; observers are marked. */
export function ParticipantNames({
  participants,
  className,
}: {
  participants: ParticipantOut[]
  className?: string
}): ReactNode {
  if (participants.length === 0) return <span className="text-muted-foreground">No interviewers</span>
  return (
    <span className={cn('inline-flex min-w-0 items-start gap-1.5 text-sm', className)}>
      <Users className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="break-words">
        {participants.map((p, i) => (
          <span key={p.user_id}>
            {i > 0 && ', '}
            {p.name}
            {p.role === 'OBSERVER' && <span className="text-muted-foreground"> (observer)</span>}
          </span>
        ))}
      </span>
    </span>
  )
}
