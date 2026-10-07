import { CalendarClock, CheckCircle2, MapPin, Wallet } from 'lucide-react'
import { Link } from 'react-router-dom'
import { MatchScoreBadge } from '@/components/common/MatchScore'
import { SkillChip } from '@/components/common/SkillChip'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { JobListItem } from '@/lib/api'
import { dates, deadlineHint, formatExperienceRange, formatSalaryRange } from '@/lib/format'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { CompanyLogo } from './CompanyLogo'
import { JobBadges } from './JobBadges'
import { SaveJobButton } from './SaveJobButton'

/**
 * Job summary card used by search, saved jobs, the landing page (and wave-2 recommendations).
 * The whole card is clickable through a stretched title link; the company link and heart sit above it.
 * Candidate-only extras (saved heart state, "Applied", match %) come straight from the API item.
 */
export function JobCard({
  job,
  highlightSkills = [],
  matchPercent,
  matchBand,
  className,
}: {
  job: JobListItem
  /** Skills the user is filtering on: shown as matched chips. */
  highlightSkills?: string[]
  /** Overrides job.match_score (e.g. recommendations carry their own percent). */
  matchPercent?: number | null
  matchBand?: string | null
  className?: string
}) {
  const { isCandidate } = useAuth()
  const salary = formatSalaryRange(job.salary_min, job.salary_max, job.salary_currency)
  const deadline = deadlineHint(job.application_deadline)
  const wanted = new Set(highlightSkills.map((s) => s.toLowerCase()))
  const skills = [...job.skills].sort(
    (a, b) => Number(wanted.has(b.toLowerCase())) - Number(wanted.has(a.toLowerCase())),
  )
  const score = matchPercent != null ? null : job.match_score

  return (
    <article
      className={cn(
        'group relative rounded-xl border bg-card p-4 shadow-xs transition-[box-shadow,border-color] duration-150 hover:border-primary/30 hover:shadow-md focus-within:border-primary/40 sm:p-5',
        className,
      )}
    >
      <div className="flex gap-3.5 sm:gap-4">
        <CompanyLogo
          name={job.company_name}
          logoUrl={job.company_logo_url}
          size="lg"
          className="hidden sm:inline-flex"
        />
        <CompanyLogo name={job.company_name} logoUrl={job.company_logo_url} size="md" className="sm:hidden" />
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-base leading-snug font-semibold tracking-tight sm:text-[17px]">
                <Link
                  to={paths.job(job.id)}
                  className="rounded-sm after:absolute after:inset-0 after:content-[''] focus-visible:outline-none group-focus-within:underline hover:underline"
                >
                  {job.title}
                </Link>
              </h3>
              <p className="mt-0.5 text-sm text-muted-foreground">
                <Link
                  to={`${paths.jobs}?company_id=${job.company_id}`}
                  className="relative z-10 rounded-sm font-medium text-foreground/80 hover:text-primary hover:underline"
                  title={`More jobs at ${job.company_name}`}
                >
                  {job.company_name}
                </Link>
                {job.department && <span> · {job.department}</span>}
              </p>
            </div>
            <div className="relative z-10 -mt-1 -mr-2 flex shrink-0 items-center gap-1">
              {job.has_applied && (
                <Badge variant="success" className="mr-1">
                  <CheckCircle2 aria-hidden /> Applied
                </Badge>
              )}
              {matchPercent != null ? (
                <MatchScoreBadge percent={matchPercent} band={matchBand} className="mr-1" />
              ) : (
                isCandidate && score != null && <MatchScoreBadge score={score} className="mr-1" />
              )}
              <SaveJobButton jobId={job.id} jobTitle={job.title} saved={job.is_saved} />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <JobBadges
              workplace={job.workplace_type}
              employment={job.employment_type}
              level={job.experience_level}
            />
            {job.location && (
              <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
                <MapPin className="size-3.5" aria-hidden />
                {job.location}
              </span>
            )}
          </div>

          {skills.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label="Required skills">
              {skills.slice(0, 6).map((s) => (
                <li key={s}>
                  <SkillChip
                    name={s}
                    tone={wanted.has(s.toLowerCase()) ? 'matched' : 'default'}
                    prefix={
                      wanted.has(s.toLowerCase()) ? (
                        <CheckCircle2 aria-label="Matches your filter" />
                      ) : undefined
                    }
                  />
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t pt-3 text-[13px] text-muted-foreground">
            {salary && (
              <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
                <Wallet className="size-3.5 text-muted-foreground" aria-hidden />
                {salary}
              </span>
            )}
            <span>{formatExperienceRange(job.min_experience_years, null)}</span>
            {job.published_at && <span>Posted {dates.relative(job.published_at)}</span>}
            {deadline && (
              <span
                className={cn(
                  'inline-flex items-center gap-1',
                  deadline.tone === 'urgent' && 'font-medium text-amber-700 dark:text-amber-400',
                  deadline.tone === 'past' && 'text-destructive',
                )}
              >
                <CalendarClock className="size-3.5" aria-hidden />
                {deadline.text}
              </span>
            )}
          </div>
        </div>
      </div>
    </article>
  )
}

export function JobCardSkeleton() {
  return (
    <div className="flex gap-4 rounded-xl border bg-card p-5" aria-hidden>
      <Skeleton className="size-14 rounded-xl" />
      <div className="flex-1 space-y-3">
        <Skeleton className="h-5 w-2/5" />
        <Skeleton className="h-4 w-1/4" />
        <div className="flex gap-2">
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-20 rounded-full" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-5 w-14 rounded-full" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-12 rounded-full" />
        </div>
        <Skeleton className="h-4 w-3/5" />
      </div>
    </div>
  )
}
