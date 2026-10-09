import { bandFromScore } from '@/components/common/MatchScore'
import type { ScoreBreakdown as Breakdown } from '@/features/matches/api/matches'
import { fmt } from '@/lib/format'
import { cn } from '@/lib/utils'
import { SCORE_COMPONENTS } from '../lib/matching'

const BAR: Record<ReturnType<typeof bandFromScore>, string> = {
  STRONG: 'bg-band-strong',
  GOOD: 'bg-band-good',
  PARTIAL: 'bg-band-partial',
  WEAK: 'bg-band-weak',
}

/**
 * Per-component scores (0..1). A `null` component is "not applicable" for this job (e.g. no preferred skills listed)
 * and is excluded from the overall score, so it is shown as such rather than as 0%.
 */
export function ScoreBreakdown({
  breakdown,
  weights,
  compact,
  className,
}: {
  breakdown: Breakdown
  /** `explanation.weights` from the match detail; shown as "weight 30%" when available. */
  weights?: Record<string, number>
  compact?: boolean
  className?: string
}) {
  return (
    <dl className={cn('grid gap-x-6 gap-y-2.5', compact ? 'sm:grid-cols-2' : 'sm:grid-cols-2', className)}>
      {SCORE_COMPONENTS.map((c) => {
        const value = breakdown[c.key]
        const weight = weights?.[c.weightKey]
        const pct = value == null ? null : Math.round(value * 100)
        return (
          <div key={c.key} className="min-w-0">
            <dt className="flex items-baseline justify-between gap-2 text-xs">
              <span className="font-medium text-foreground" title={c.help}>
                {c.label}
                {weight !== undefined && !compact && (
                  <span className="ml-1.5 font-normal text-muted-foreground">
                    weight {fmt.percent(weight)}
                  </span>
                )}
              </span>
              <span className="font-semibold tabular">
                {pct === null ? <span className="font-normal text-muted-foreground">n/a</span> : `${pct}%`}
              </span>
            </dt>
            <dd className="mt-1">
              <div
                role="meter"
                aria-label={c.label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct ?? undefined}
                aria-valuetext={pct === null ? 'Not applicable for this job' : `${pct}%`}
                className="h-1.5 overflow-hidden rounded-full bg-muted"
              >
                {value != null && (
                  <div
                    className={cn('h-full rounded-full', BAR[bandFromScore(value)])}
                    style={{ width: `${Math.max(2, pct ?? 0)}%` }}
                  />
                )}
              </div>
            </dd>
          </div>
        )
      })}
    </dl>
  )
}
