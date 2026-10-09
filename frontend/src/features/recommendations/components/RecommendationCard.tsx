import { Check, ChevronDown, CircleAlert } from 'lucide-react'
import { useId, useState } from 'react'
import { JobCard } from '@/features/jobs/components/JobCard'
import { MatchExplanation } from '@/features/jobs/components/MatchCard'
import { cn } from '@/lib/utils'
import type { RecommendedJob } from '../api/recommendations'

/** A job card with its real match score and a "Why this match?" disclosure (strong / related / missing skills). */
export function RecommendationCard({ item }: { item: RecommendedJob }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const { job, match } = item
  return (
    <li>
      <JobCard
        job={job}
        matchPercent={match.overall_percent}
        matchBand={match.band}
        className="rounded-b-none border-b-0"
      />
      <div className="rounded-b-xl border border-t bg-card px-4 py-2 shadow-xs sm:px-5">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((o) => !o)}
          className="flex w-full cursor-pointer flex-wrap items-center gap-x-4 gap-y-1 rounded-md py-1 text-left text-sm focus-visible:outline-2 focus-visible:outline-ring"
        >
          <span className="font-medium text-primary">Why this match?</span>
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Check className="size-3.5 text-emerald-600" aria-hidden />
            {match.matched_skills.length} skill{match.matched_skills.length === 1 ? '' : 's'} matched
          </span>
          {match.missing_required.length > 0 && (
            <span className="inline-flex items-center gap-1 text-muted-foreground">
              <CircleAlert className="size-3.5 text-amber-600" aria-hidden />
              {match.missing_required.length} required to build
            </span>
          )}
          <ChevronDown
            className={cn('ml-auto size-4 transition-transform', open && 'rotate-180')}
            aria-hidden
          />
        </button>
        <div id={panelId} hidden={!open} className="pt-3 pb-2">
          {open && <MatchExplanation match={match} />}
        </div>
      </div>
    </li>
  )
}
