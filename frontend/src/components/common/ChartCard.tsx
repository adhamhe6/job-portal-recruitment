import type { ReactNode } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { ErrorState } from './States'

/**
 * Card shell for a Recharts chart: title + description, loading skeleton, error state and an accessible figure.
 * Always pass a `description` that states what the chart shows, and render a data table / summary via `srSummary`
 * for screen-reader users (charts themselves are not readable by assistive tech).
 */
export function ChartCard({
  title,
  description,
  action,
  loading,
  error,
  onRetry,
  height = 260,
  srSummary,
  className,
  children,
}: {
  title: string
  description?: string
  action?: ReactNode
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  height?: number
  /** Text alternative of the data (e.g. "Applied 4, Screening 2, …"). */
  srSummary?: string
  className?: string
  children: ReactNode
}) {
  return (
    <Card className={cn('flex flex-col', className)}>
      <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
        <div className="grid gap-1">
          <CardTitle>{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        {action}
      </CardHeader>
      <CardContent className="flex-1">
        {error ? (
          <ErrorState error={error} onRetry={onRetry} compact />
        ) : loading ? (
          <Skeleton style={{ height }} className="w-full" />
        ) : (
          <figure
            role="img"
            aria-label={`${title}. ${srSummary ?? description ?? ''}`.trim()}
            style={{ height }}
            className="m-0"
          >
            {children}
          </figure>
        )}
      </CardContent>
    </Card>
  )
}

/** Shared Recharts styling so every chart looks consistent (tokens switch with the theme). */
export const chartTheme = {
  grid: 'var(--border)',
  axis: { fontSize: 12, fill: 'var(--muted-foreground)' },
  tooltip: {
    contentStyle: {
      background: 'var(--popover)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      fontSize: 12,
      color: 'var(--popover-foreground)',
      boxShadow: '0 8px 24px -8px rgb(0 0 0 / 0.25)',
    },
    labelStyle: { fontWeight: 600, marginBottom: 4 },
    cursor: { fill: 'var(--muted)', opacity: 0.6 },
  },
  /** Categorical series colours in fixed order (never cycle; fold extras into "Other"). */
  colors: ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)'],
}
