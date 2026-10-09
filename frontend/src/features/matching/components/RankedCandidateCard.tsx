import { Briefcase, ChevronDown, Clock, ExternalLink, MapPin, UserRound } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { MatchScoreBadge } from '@/components/common/MatchScore'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { AVAILABILITY_LABELS, type Availability } from '@/features/candidates/lib/filters'
import type { MatchedCandidate } from '@/features/matches/api/matches'
import { fmt } from '@/lib/format'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { ScoreBreakdown } from './ScoreBreakdown'
import { SkillGroups, toRelated } from './SkillGroups'

export function candidateLink(candidateId: string, jobId: string) {
  return `${paths.candidate(candidateId)}?job_id=${encodeURIComponent(jobId)}`
}

/** One ranked candidate: overall score, short explanation, expandable per-component breakdown and skill gaps. */
export function RankedCandidateCard({
  match,
  jobId,
  rank,
}: {
  match: MatchedCandidate
  jobId: string
  rank: number
}) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const availability = match.availability
    ? (AVAILABILITY_LABELS[match.availability as Availability] ?? fmt.label(match.availability))
    : null

  return (
    <article
      aria-label={`${match.display_name}, ${match.overall_percent}% match`}
      className="rounded-xl border bg-card p-4 shadow-xs sm:p-5"
    >
      <div className="flex gap-3.5">
        <div className="hidden flex-col items-center gap-1 sm:flex">
          <Avatar name={match.display_name} size="lg" />
          <span className="text-xs text-muted-foreground tabular" aria-label={`Rank ${rank}`}>
            #{rank}
          </span>
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <h3 className="text-base font-semibold break-words">
                <Link
                  to={candidateLink(match.candidate_id, jobId)}
                  className="rounded-sm hover:text-primary hover:underline"
                >
                  {match.display_name}
                </Link>
              </h3>
              {match.headline && <p className="text-sm text-muted-foreground">{match.headline}</p>}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {match.stale && (
                <Badge variant="warning" title="Computed before the candidate or job changed">
                  Out of date
                </Badge>
              )}
              <MatchScoreBadge
                percent={match.overall_percent}
                band={match.band}
                showLabel
                className="text-sm"
              />
            </div>
          </div>

          <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {match.location && (
              <li className="flex items-center gap-1.5">
                <MapPin className="size-3.5" aria-hidden /> {match.location}
              </li>
            )}
            {match.years_experience && (
              <li className="flex items-center gap-1.5">
                <Briefcase className="size-3.5" aria-hidden /> {fmt.num(match.years_experience)} yrs
                experience
              </li>
            )}
            {availability && (
              <li className="flex items-center gap-1.5">
                <Clock className="size-3.5" aria-hidden /> {availability}
              </li>
            )}
            {match.access === 'PROFILE' && (
              <li className="flex items-center gap-1.5">
                <UserRound className="size-3.5" aria-hidden /> Marketplace profile
              </li>
            )}
          </ul>

          <p className="text-sm">{match.summary}</p>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <button
              type="button"
              aria-expanded={open}
              aria-controls={panelId}
              onClick={() => setOpen((o) => !o)}
              className="inline-flex cursor-pointer items-center gap-1 rounded-sm text-sm font-medium text-primary hover:underline"
            >
              Why this score
              <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} aria-hidden />
            </button>
            <Link
              to={candidateLink(match.candidate_id, jobId)}
              className="inline-flex items-center gap-1 rounded-sm text-sm font-medium hover:text-primary hover:underline"
            >
              Full profile and explanation
            </Link>
            {match.has_applied && match.application_id && (
              <Link
                to={paths.application(match.application_id)}
                className="inline-flex items-center gap-1.5 rounded-sm text-sm font-medium hover:text-primary hover:underline"
              >
                <ExternalLink className="size-3.5" aria-hidden /> View application
                {match.application_status && (
                  <StatusBadge kind="application" status={match.application_status} />
                )}
              </Link>
            )}
            {!match.has_applied && <span className="text-xs text-muted-foreground">Has not applied</span>}
          </div>

          {open && (
            <div id={panelId} className="space-y-4 rounded-lg bg-surface p-3.5">
              <ScoreBreakdown breakdown={match.breakdown} compact />
              <SkillGroups
                strong={match.strong_skills}
                related={toRelated(match.related_skills)}
                missingRequired={match.missing_required}
                missingPreferred={match.missing_preferred}
              />
              <p className="text-sm">
                <span className="text-muted-foreground">Experience: </span>
                {match.experience_text}
              </p>
            </div>
          )}
        </div>
      </div>
    </article>
  )
}

export function RankedCandidateSkeleton() {
  return (
    <div className="flex gap-4 rounded-xl border bg-card p-5">
      <Skeleton className="hidden size-14 rounded-full sm:block" />
      <div className="flex-1 space-y-3">
        <Skeleton className="h-5 w-1/3" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    </div>
  )
}
