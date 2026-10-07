import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface ActiveFilter {
  key: string
  label: string
  onRemove: () => void
}

/**
 * Toolbar row above a list: search / selects / toggles on the left, extras (sort, view switch) on the right,
 * plus removable chips for the active filters and a "Clear all" action.
 */
export function FilterBar({
  children,
  trailing,
  active = [],
  onClearAll,
  className,
}: {
  children?: ReactNode
  trailing?: ReactNode
  active?: ActiveFilter[]
  onClearAll?: () => void
  className?: string
}) {
  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex flex-wrap items-center gap-2">
        {children}
        {trailing && <div className="ml-auto flex flex-wrap items-center gap-2">{trailing}</div>}
      </div>
      {active.length > 0 && (
        <ul className="flex flex-wrap items-center gap-2" aria-label="Active filters">
          {active.map((f) => (
            <li key={f.key}>
              <span className="inline-flex items-center gap-1 rounded-full border bg-card py-0.5 pr-1 pl-3 text-xs font-medium">
                {f.label}
                <button
                  type="button"
                  onClick={f.onRemove}
                  aria-label={`Remove filter: ${f.label}`}
                  className="inline-flex size-5 cursor-pointer items-center justify-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <X className="size-3" aria-hidden />
                </button>
              </span>
            </li>
          ))}
          {onClearAll && active.length > 1 && (
            <li>
              <Button variant="link" size="sm" className="text-xs" onClick={onClearAll}>
                Clear all
              </Button>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
