import { Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SCORE_COMPONENTS, SCORE_DISCLAIMER } from '../lib/matching'

/** "What the score means and does not mean" - collapsible so it does not crowd the ranking. */
export function ScoreDisclaimer({
  className,
  defaultOpen = false,
}: {
  className?: string
  defaultOpen?: boolean
}) {
  return (
    <details open={defaultOpen} className={cn('group rounded-lg border bg-surface text-sm', className)}>
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-3.5 py-2.5 font-medium select-none focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
        <Info className="size-4 shrink-0 text-primary" aria-hidden />
        How to read match scores
        <span className="ml-auto text-xs font-normal text-muted-foreground group-open:hidden">Show</span>
        <span className="ml-auto hidden text-xs font-normal text-muted-foreground group-open:inline">
          Hide
        </span>
      </summary>
      <div className="space-y-3 border-t px-3.5 py-3 text-muted-foreground">
        <p>{SCORE_DISCLAIMER}</p>
        <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {SCORE_COMPONENTS.map((c) => (
            <li key={c.key}>
              <span className="font-medium text-foreground">{c.label}.</span> {c.help}
            </li>
          ))}
        </ul>
        <p>
          Components that do not apply to a job (for example, no preferred skills) are left out and the
          remaining weights are rescaled. A candidate who covers very few required skills is capped at a
          partial match.
        </p>
      </div>
    </details>
  )
}
