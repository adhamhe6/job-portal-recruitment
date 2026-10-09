import { Briefcase, Clock, Laptop, MapPin } from 'lucide-react'
import { Link } from 'react-router-dom'
import { MatchScoreBadge } from '@/components/common/MatchScore'
import { SkillChip } from '@/components/common/SkillChip'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import type { CandidateListItem } from '../api/candidates'
import {
  AVAILABILITY_LABELS,
  REMOTE_PREFERENCE_LABELS,
  type Availability,
  type RemotePreference,
} from '../lib/filters'

/**
 * Search result. Only fields the API releases for this access level are shown (marketplace profiles carry no contact
 * details). The whole card is clickable through a stretched name link.
 */
export function CandidateCard({ candidate: c, jobId }: { candidate: CandidateListItem; jobId?: string }) {
  const to = jobId ? `${paths.candidate(c.id)}?job_id=${encodeURIComponent(jobId)}` : paths.candidate(c.id)
  const matched = new Set((c.skill_matches ?? []).map((s) => s.toLowerCase()))
  const skills = [...c.top_skills].sort(
    (a, b) => Number(matched.has(b.toLowerCase())) - Number(matched.has(a.toLowerCase())),
  )
  const shown = skills.slice(0, 8)
  const rest = skills.length - shown.length
  const availability = c.availability
    ? (AVAILABILITY_LABELS[c.availability as Availability] ?? fmt.label(c.availability))
    : null
  const remote = c.remote_preference
    ? (REMOTE_PREFERENCE_LABELS[c.remote_preference as RemotePreference] ?? fmt.label(c.remote_preference))
    : null

  return (
    <article className="group relative rounded-xl border bg-card p-4 shadow-xs transition-[box-shadow,border-color] duration-150 focus-within:border-primary/40 hover:border-primary/30 hover:shadow-md sm:p-5">
      <div className="flex gap-3.5">
        <Avatar name={c.display_name} size="lg" className="hidden sm:inline-flex" />
        <Avatar name={c.display_name} size="md" className="sm:hidden" />
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <h3 className="text-base font-semibold break-words">
                <Link
                  to={to}
                  className="rounded-sm after:absolute after:inset-0 after:content-[''] hover:text-primary"
                >
                  {c.display_name}
                </Link>
              </h3>
              {c.headline && <p className="text-sm text-muted-foreground">{c.headline}</p>}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {c.has_applied && <Badge variant="info">Applied to your jobs</Badge>}
              {c.source === 'IMPORTED' && <Badge variant="violet">Imported</Badge>}
              {c.access === 'PROFILE' && <Badge variant="muted">Marketplace profile</Badge>}
              {c.match_score != null && (
                <MatchScoreBadge score={c.match_score} band={c.match_band} showLabel className="text-sm" />
              )}
            </div>
          </div>

          <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {c.location && (
              <li className="flex items-center gap-1.5">
                <MapPin className="size-3.5" aria-hidden /> {c.location}
              </li>
            )}
            {c.years_experience != null && (
              <li className="flex items-center gap-1.5">
                <Briefcase className="size-3.5" aria-hidden /> {fmt.num(c.years_experience)} yrs experience
              </li>
            )}
            {availability && (
              <li className="flex items-center gap-1.5">
                <Clock className="size-3.5" aria-hidden /> {availability}
              </li>
            )}
            {remote && (
              <li className="flex items-center gap-1.5">
                <Laptop className="size-3.5" aria-hidden /> {remote}
              </li>
            )}
          </ul>

          {shown.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5" aria-label="Skills">
              {shown.map((s) => (
                <li key={s}>
                  <SkillChip name={s} tone={matched.has(s.toLowerCase()) ? 'matched' : 'default'} />
                </li>
              ))}
              {rest > 0 && (
                <li>
                  <SkillChip name={`+${rest}`} tone="muted" />
                </li>
              )}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No skills listed.</p>
          )}
        </div>
      </div>
    </article>
  )
}

export function CandidateCardSkeleton() {
  return (
    <div className="flex gap-4 rounded-xl border bg-card p-5" aria-hidden>
      <Skeleton className="hidden size-14 rounded-full sm:block" />
      <div className="flex-1 space-y-3">
        <Skeleton className="h-5 w-1/3" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-2/3" />
        <div className="flex gap-2">
          <Skeleton className="h-6 w-16 rounded-full" />
          <Skeleton className="h-6 w-20 rounded-full" />
          <Skeleton className="h-6 w-14 rounded-full" />
        </div>
      </div>
    </div>
  )
}
