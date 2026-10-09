import { RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { MatchBar } from '@/components/common/MatchScore'
import { ErrorState } from '@/components/common/States'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { useMatchDetail } from '@/features/matches/api/matches'
import { dates } from '@/lib/format'
import { paths } from '@/routes/paths'
import {
  parseExplanation,
  REQUIREMENT_STATUS_LABELS,
  SEMANTIC_LABELS,
  type SkillGroup,
} from '../lib/matching'
import { ScoreBreakdown } from './ScoreBreakdown'
import { ScoreDisclaimer } from './ScoreDisclaimer'
import { SkillGroups } from './SkillGroups'

function groupAsProps(required: SkillGroup | null, preferred: SkillGroup | null) {
  return {
    strong: [...(required?.matched ?? []), ...(preferred?.matched ?? [])],
    related: [...(required?.related ?? []), ...(preferred?.related ?? [])],
    missingRequired: required?.missing ?? [],
    missingPreferred: preferred?.missing ?? [],
  }
}

/** Full, explained match of one candidate against one job (GET /matches/jobs/{job}/candidates/{candidate}). */
export function MatchDetailPanel({ jobId, candidateId }: { jobId: string; candidateId: string }) {
  const { data, isPending, isError, error, refetch } = useMatchDetail(jobId, candidateId)

  if (isPending)
    return (
      <div className="space-y-3" role="status" aria-busy="true" aria-label="Loading match">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  if (isError)
    return <ErrorState compact error={error} onRetry={() => refetch()} title="Couldn't load this match" />
  if (!data)
    return (
      <div className="space-y-3 rounded-lg border border-dashed p-4 text-sm">
        <p className="text-muted-foreground">
          No match has been computed for this candidate and job yet. Matches are calculated in the background;
          open the job’s ranking to refresh them.
        </p>
        <Button asChild variant="outline" size="sm">
          <Link to={paths.matchingJob(jobId)}>
            <RefreshCw /> Open ranking for this job
          </Link>
        </Button>
      </div>
    )

  const ex = parseExplanation(data.explanation)
  return (
    <div className="space-y-5">
      <MatchBar percent={data.overall_percent} band={data.band} label={`Match with ${data.job_title}`} />
      {ex.summary && <p className="text-sm">{ex.summary}</p>}
      {ex.qualificationFloorApplied && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          Few of the required skills were found, so the overall score is capped at a partial match whatever
          the other components say.
        </p>
      )}

      <section aria-labelledby="breakdown-h" className="space-y-2.5">
        <h3 id="breakdown-h" className="text-sm font-semibold">
          Score breakdown
        </h3>
        <ScoreBreakdown breakdown={data.breakdown} weights={ex.weights} />
      </section>

      <section aria-labelledby="skills-h" className="space-y-2.5">
        <h3 id="skills-h" className="text-sm font-semibold">
          Skills
        </h3>
        <SkillGroups {...groupAsProps(ex.required, ex.preferred)} />
        {(ex.required || ex.preferred) && (
          <p className="text-xs text-muted-foreground">
            {ex.required && `Required: ${ex.required.matched.length} of ${ex.required.total} matched. `}
            {ex.preferred && `Nice to have: ${ex.preferred.matched.length} of ${ex.preferred.total} matched.`}
          </p>
        )}
      </section>

      <dl className="grid gap-3 rounded-lg bg-surface p-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">Experience</dt>
          <dd className="font-medium">{ex.experience?.text ?? '—'}</dd>
          {ex.experience?.status && (
            <dd className="text-xs text-muted-foreground">
              {REQUIREMENT_STATUS_LABELS[ex.experience.status] ?? ex.experience.status}
            </dd>
          )}
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Education</dt>
          <dd className="font-medium">
            {ex.education?.status
              ? (REQUIREMENT_STATUS_LABELS[ex.education.status] ?? ex.education.status)
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Profile relevance</dt>
          <dd className="font-medium">
            {ex.semantic?.band ? (SEMANTIC_LABELS[ex.semantic.band] ?? ex.semantic.band) : '—'}
          </dd>
        </div>
        {ex.preferences.map((p) => (
          <div key={p.label} className="sm:col-span-3">
            <dt className="text-xs text-muted-foreground">{p.label}</dt>
            <dd className="font-medium">{p.value}</dd>
          </div>
        ))}
      </dl>

      <p className="text-xs text-muted-foreground">
        Calculated {dates.relative(data.generated_at)} with {data.embedding_model} (matching{' '}
        {data.matching_version}).
      </p>
      <ScoreDisclaimer />
    </div>
  )
}
