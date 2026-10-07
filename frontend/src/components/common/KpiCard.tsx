import { TrendingDown, TrendingUp } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const TONES = {
  default: 'bg-primary-soft text-primary-soft-foreground',
  success: 'bg-emerald-500/12 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300',
  warning: 'bg-amber-500/15 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300',
  danger: 'bg-red-500/12 text-red-700 dark:bg-red-400/15 dark:text-red-300',
  info: 'bg-sky-500/12 text-sky-700 dark:bg-sky-400/15 dark:text-sky-300',
}

/**
 * Headline number tile.
 *
 *   <KpiCard label="Open jobs" value={12} icon={<Briefcase />} hint="3 closing soon" to="/manage/jobs" />
 */
export function KpiCard({
  label,
  value,
  hint,
  icon,
  tone = 'default',
  change,
  to,
  loading,
  className,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  icon?: ReactNode
  tone?: keyof typeof TONES
  /** Percent change vs previous period; sign decides the arrow. */
  change?: number | null
  /** Makes the whole card a link. */
  to?: string
  loading?: boolean
  className?: string
}) {
  const body = (
    <Card className={cn('h-full p-5 transition-shadow', to && 'hover:shadow-md', className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          {loading ? (
            <Skeleton className="mt-2 h-8 w-20" />
          ) : (
            <p className="mt-1.5 text-3xl font-semibold tracking-tight">{value}</p>
          )}
        </div>
        {icon && (
          <div
            className={cn(
              'flex size-10 shrink-0 items-center justify-center rounded-xl [&_svg]:size-5',
              TONES[tone],
            )}
          >
            {icon}
          </div>
        )}
      </div>
      {(hint || (change !== undefined && change !== null)) && !loading && (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          {change !== undefined && change !== null && (
            <span
              className={cn(
                'inline-flex items-center gap-0.5 font-semibold',
                change >= 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-red-400',
              )}
            >
              {change >= 0 ? (
                <TrendingUp className="size-3.5" aria-hidden />
              ) : (
                <TrendingDown className="size-3.5" aria-hidden />
              )}
              {change > 0 ? '+' : ''}
              {change.toFixed(1)}%
            </span>
          )}
          {hint}
        </div>
      )}
    </Card>
  )
  return to ? (
    <Link to={to} className="block rounded-xl">
      {body}
    </Link>
  ) : (
    body
  )
}
