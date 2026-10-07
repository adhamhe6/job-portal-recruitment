import { ArrowRightLeft, Check, CircleDashed, Sparkles, X } from 'lucide-react'
import { MatchBar } from '@/components/common/MatchScore'
import { SkillChip } from '@/components/common/SkillChip'
import { ErrorState } from '@/components/common/States'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useMyJobMatch } from '@/features/matches/api/matches'
import type { CandidateFacingMatch } from '@/lib/api'
import { dates } from '@/lib/format'
import { cn } from '@/lib/utils'

const SEMANTIC_LABELS: Record<string, string> = { HIGH: 'High', MEDIUM: 'Medium', MED: 'Medium', LOW: 'Low' }
const EXPERIENCE_TONE: Record<string, string> = {
  MEETS: 'text-emerald-700 dark:text-emerald-400',
  EXCEEDS: 'text-emerald-700 dark:text-emerald-400',
  BELOW: 'text-amber-700 dark:text-amber-400',
  UNKNOWN: 'text-muted-foreground',
}

function Group({
  title,
  icon,
  children,
}: {
  title: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <h4 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase [&_svg]:size-3.5">
        {icon}
        {title}
      </h4>
      {children}
    </div>
  )
}

/** Presentational explanation of a candidate↔job match (real data from GET /matches/me/jobs/{id}). */
export function MatchExplanation({ match }: { match: CandidateFacingMatch }) {
  const related = match.related_skills.map((r) => ({
    key: `${r.required}-${r.candidate_has}`,
    label: `${r.candidate_has ?? '?'} ≈ ${r.required ?? '?'}`,
  }))
  return (
    <div className="space-y-4">
      <MatchBar percent={match.overall_percent} band={match.band} label="Your match with this job" />
      <p className="text-sm text-muted-foreground">{match.summary}</p>

      {match.matched_skills.length > 0 && (
        <Group title="Skills you have" icon={<Check />}>
          <ul className="flex flex-wrap gap-1.5">
            {match.matched_skills.map((s) => (
              <li key={s}>
                <SkillChip name={s} tone="matched" prefix={<Check aria-label="Matched" />} />
              </li>
            ))}
          </ul>
        </Group>
      )}
      {related.length > 0 && (
        <Group title="Related experience" icon={<ArrowRightLeft />}>
          <ul className="flex flex-wrap gap-1.5">
            {related.map((r) => (
              <li key={r.key}>
                <SkillChip name={r.label} tone="related" />
              </li>
            ))}
          </ul>
        </Group>
      )}
      {match.missing_required.length > 0 && (
        <Group title="Required skills to build" icon={<X />}>
          <ul className="flex flex-wrap gap-1.5">
            {match.missing_required.map((s) => (
              <li key={s}>
                <SkillChip name={s} tone="missing" />
              </li>
            ))}
          </ul>
        </Group>
      )}
      {match.missing_preferred.length > 0 && (
        <Group title="Nice to have" icon={<CircleDashed />}>
          <ul className="flex flex-wrap gap-1.5">
            {match.missing_preferred.map((s) => (
              <li key={s}>
                <SkillChip name={s} tone="preferred" />
              </li>
            ))}
          </ul>
        </Group>
      )}

      <dl className="grid grid-cols-2 gap-3 rounded-lg bg-surface p-3 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Experience</dt>
          <dd className={cn('font-medium', EXPERIENCE_TONE[match.experience_status] ?? '')}>
            {match.experience_text}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Profile relevance</dt>
          <dd className="font-medium">{SEMANTIC_LABELS[match.semantic_band] ?? match.semantic_band}</dd>
        </div>
      </dl>
      <p className="text-xs text-muted-foreground">
        A ranking aid based on your profile and résumé, not a hiring decision. Updated{' '}
        {dates.relative(match.generated_at)}.
      </p>
    </div>
  )
}

/** "How you match" card for candidates. Renders nothing when no match exists for this job (404). */
export function MatchCard({ jobId }: { jobId: string }) {
  const { data, isPending, isError, error, refetch } = useMyJobMatch(jobId)
  if (isPending) {
    return (
      <Card aria-busy="true">
        <CardHeader>
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </CardContent>
      </Card>
    )
  }
  if (isError) {
    return (
      <Card>
        <ErrorState compact error={error} onRetry={() => refetch()} title="Couldn't load your match" />
      </Card>
    )
  }
  if (!data) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" aria-hidden /> How you match
        </CardTitle>
        <CardDescription>Based on your profile and résumé</CardDescription>
      </CardHeader>
      <CardContent>
        <MatchExplanation match={data} />
      </CardContent>
    </Card>
  )
}
