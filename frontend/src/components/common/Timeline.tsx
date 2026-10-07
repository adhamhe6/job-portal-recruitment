import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface TimelineItem {
  id: string
  title: ReactNode
  description?: ReactNode
  /** Right-aligned or under-title time text. */
  time?: ReactNode
  icon?: ReactNode
  tone?: 'default' | 'success' | 'danger' | 'warning' | 'muted'
}

const DOT = {
  default: 'bg-primary-soft text-primary-soft-foreground ring-primary/20',
  success: 'bg-emerald-500/15 text-emerald-700 ring-emerald-500/25 dark:text-emerald-300',
  danger: 'bg-red-500/12 text-red-700 ring-red-500/25 dark:text-red-300',
  warning: 'bg-amber-500/15 text-amber-800 ring-amber-500/30 dark:text-amber-300',
  muted: 'bg-muted text-muted-foreground ring-border',
}

/** Vertical event timeline (application history, status changes, activity). Newest first is the caller's choice. */
export function Timeline({ items, className }: { items: TimelineItem[]; className?: string }) {
  return (
    <ol className={cn('relative space-y-5', className)}>
      {items.map((item, i) => (
        <li key={item.id} className="relative flex gap-3">
          {i < items.length - 1 && <span className="absolute top-8 bottom-[-1.25rem] left-[15px] w-px bg-border" aria-hidden />}
          <span className={cn('z-10 flex size-8 shrink-0 items-center justify-center rounded-full ring-4 ring-card [&_svg]:size-4', DOT[item.tone ?? 'default'])}>
            {item.icon ?? <span className="size-2 rounded-full bg-current" />}
          </span>
          <div className="min-w-0 flex-1 pt-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <p className="text-sm font-medium">{item.title}</p>
              {item.time && <p className="text-xs text-muted-foreground">{item.time}</p>}
            </div>
            {item.description && <p className="mt-0.5 text-sm text-muted-foreground">{item.description}</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}
