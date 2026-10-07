import { Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

export type MatchBand = 'STRONG' | 'GOOD' | 'PARTIAL' | 'WEAK'

/** Same thresholds as the backend (matching/scoring.py::overall_band). */
export function bandFromScore(score: number): MatchBand {
  return score >= 0.75 ? 'STRONG' : score >= 0.55 ? 'GOOD' : score >= 0.35 ? 'PARTIAL' : 'WEAK'
}

export function normalizeBand(band: string | null | undefined, score?: number | null): MatchBand {
  const b = band?.toUpperCase()
  if (b === 'STRONG' || b === 'GOOD' || b === 'PARTIAL' || b === 'WEAK') return b
  return score != null ? bandFromScore(score) : 'WEAK'
}

export const BAND_LABELS: Record<MatchBand, string> = {
  STRONG: 'Strong match',
  GOOD: 'Good match',
  PARTIAL: 'Partial match',
  WEAK: 'Weak match',
}

const BAND_STYLES: Record<MatchBand, { badge: string; text: string; bar: string }> = {
  STRONG: {
    badge: 'bg-[color-mix(in_oklch,var(--band-strong)_14%,transparent)] text-band-strong',
    text: 'text-band-strong',
    bar: 'bg-band-strong',
  },
  GOOD: {
    badge: 'bg-[color-mix(in_oklch,var(--band-good)_14%,transparent)] text-band-good',
    text: 'text-band-good',
    bar: 'bg-band-good',
  },
  PARTIAL: {
    badge: 'bg-[color-mix(in_oklch,var(--band-partial)_16%,transparent)] text-band-partial',
    text: 'text-band-partial',
    bar: 'bg-band-partial',
  },
  WEAK: {
    badge: 'bg-[color-mix(in_oklch,var(--band-weak)_14%,transparent)] text-band-weak',
    text: 'text-band-weak',
    bar: 'bg-band-weak',
  },
}

interface ScoreInput {
  /** 0..1 */
  score?: number | null
  /** 0..100 (alternative to score) */
  percent?: number | null
  band?: string | null
}

function resolve({ score, percent, band }: ScoreInput) {
  const pct = percent != null ? Math.round(percent) : score != null ? Math.round(score * 100) : null
  const s = score ?? (percent != null ? percent / 100 : null)
  return { pct, band: normalizeBand(band, s) }
}

/** "92% match" pill, coloured by band. Renders nothing when there is no score. */
export function MatchScoreBadge({ className, showLabel = false, ...input }: ScoreInput & { className?: string; showLabel?: boolean }) {
  const { pct, band } = resolve(input)
  if (pct === null) return null
  return (
    <span
      className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap', BAND_STYLES[band].badge, className)}
      title={`${BAND_LABELS[band]} (${pct}%)`}
    >
      <Sparkles className="size-3" aria-hidden />
      <span className="tabular">{pct}%</span>
      <span className={showLabel ? '' : 'sr-only'}>{showLabel ? BAND_LABELS[band].replace(' match', '') : BAND_LABELS[band]}</span>
    </span>
  )
}

/** Horizontal meter with percentage + band label. */
export function MatchBar({ className, label = 'Match score', ...input }: ScoreInput & { className?: string; label?: string }) {
  const { pct, band } = resolve(input)
  if (pct === null) return null
  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">{BAND_LABELS[band]}</span>
        <span className={cn('text-lg font-semibold tabular', BAND_STYLES[band].text)}>{pct}%</span>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={`${pct}% — ${BAND_LABELS[band]}`}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div className={cn('h-full rounded-full transition-[width] duration-500', BAND_STYLES[band].bar)} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  )
}
