import { Check, CircleDashed, Sparkles, X } from 'lucide-react'
import { MatchBar } from '@/components/common/MatchScore'
import { SkillChip } from '@/components/common/SkillChip'
import { ErrorState } from '@/components/common/States'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { ApplicationDetail } from '@/lib/api'
import { dates } from '@/lib/format'
import { useApplicationMatch } from '../api/applications'
import { parseExplanation, type SkillGroup } from '../lib/match'

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
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  )
}

function SkillsBlock({ label, group }: { label: string; group: SkillGroup }) {
  if (group.total === 0 && !group.matched.length && !group.missing.length && !group.related.length)
    return null
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">
        {label}
        {group.total > 0 && (
          <span className="ml-2 font-normal text-muted-foreground">
            {group.matched.length} of {group.total} covered
          </span>
        )}
      </p>
      {group.matched.length > 0 && (
        <Group title="Strong — has" icon={<Check aria-hidden />}>
          {group.matched.map((n) => (
            <SkillChip key={n} name={n} tone="matched" />
          ))}
        </Group>
      )}
      {group.related.length > 0 && (
        <Group title="Related — close alternative" icon={<CircleDashed aria-hidden />}>
          {group.related.map((r) => (
            <SkillChip
              key={`${r.required}-${r.candidateHas}`}
              name={`${r.candidateHas || '?'} ≈ ${r.required}`}
              tone="related"
            />
          ))}
        </Group>
      )}
      {group.missing.length > 0 && (
        <Group title="Missing" icon={<X aria-hidden />}>
          {group.missing.map((n) => (
            <SkillChip key={n} name={n} tone="missing" />
          ))}
        </Group>
      )}
    </div>
  )
}

/**
 * Staff-only "why this score" card. The headline (score, band, summary) comes with the application; the skill
 * breakdown is loaded from the match endpoint and degrades gracefully when no detailed match exists.
 */
export function MatchPanel({ application }: { application: ApplicationDetail }) {
  const basic = application.match as
    { overall_score?: number; band?: string; summary?: string } | null | undefined
  const detail = useApplicationMatch(application.job_id, application.candidate_id, true)
  const insight = detail.data ? parseExplanation(detail.data.explanation) : null

  if (!basic && !detail.isPending && !detail.data && !detail.isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="size-4 text-primary" aria-hidden /> Match
          </CardTitle>
          <CardDescription>No match score has been computed for this application yet.</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="size-4 text-primary" aria-hidden /> Match with this job
        </CardTitle>
        <CardDescription>
          A ranking aid based on skills, experience and profile — not a hiring decision.
          {detail.data && ` Computed ${dates.relative(detail.data.generated_at)}.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {basic?.overall_score != null && (
          <MatchBar score={basic.overall_score} band={basic.band} label="Match score" />
        )}
        {(insight?.summary ?? basic?.summary) && (
          <p className="text-sm text-muted-foreground">{insight?.summary ?? basic?.summary}</p>
        )}
        {detail.isPending ? (
          <div className="space-y-2" role="status" aria-label="Loading skill breakdown">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-2/3" />
          </div>
        ) : detail.isError ? (
          <ErrorState
            error={detail.error}
            onRetry={() => detail.refetch()}
            compact
            title="Couldn't load the skill breakdown"
          />
        ) : insight ? (
          <>
            <SkillsBlock label="Required skills" group={insight.required} />
            <SkillsBlock label="Preferred skills" group={insight.preferred} />
            {insight.experienceText && (
              <p className="text-sm">
                <span className="font-medium">Experience: </span>
                <span className="text-muted-foreground">{insight.experienceText}</span>
              </p>
            )}
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}
