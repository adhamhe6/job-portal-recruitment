import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'

export interface Crumb {
  label: string
  /** Omit for the current page. */
  to?: string
}

export function Breadcrumbs({ items, className }: { items: Crumb[]; className?: string }) {
  if (items.length === 0) return null
  return (
    <nav aria-label="Breadcrumb" className={className}>
      <ol className="flex flex-wrap items-center gap-1 text-[13px] text-muted-foreground">
        {items.map((c, i) => {
          const last = i === items.length - 1
          return (
            <li key={`${c.label}-${i}`} className="flex min-w-0 items-center gap-1">
              {c.to && !last ? (
                <Link to={c.to} className="rounded-sm hover:text-foreground hover:underline">
                  {c.label}
                </Link>
              ) : (
                <span aria-current={last ? 'page' : undefined} className={cn('truncate', last && 'font-medium text-foreground')}>
                  {c.label}
                </span>
              )}
              {!last && <ChevronRight className="size-3.5 shrink-0" aria-hidden />}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/**
 * Page title block: breadcrumbs, <h1>, description and right-aligned actions. Every page has exactly one.
 *
 *   <PageHeader title="Jobs" description="…" breadcrumbs={[{label:'Home',to:'/'},{label:'Jobs'}]} actions={<Button>New</Button>} />
 */
export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  meta,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  breadcrumbs?: Crumb[]
  actions?: ReactNode
  /** Row of badges / small facts under the title. */
  meta?: ReactNode
  className?: string
}) {
  return (
    <header className={cn('mb-6 flex flex-col gap-3', className)}>
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight break-words sm:text-[1.7rem]">{title}</h1>
          {description && <p className="max-w-2xl text-sm text-muted-foreground sm:text-[15px]">{description}</p>}
          {meta && <div className="flex flex-wrap items-center gap-2 pt-1">{meta}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}
