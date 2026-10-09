import type { ReactNode } from 'react'
import { ErrorState } from '@/components/common/States'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/** Card for a non-chart report section with loading skeleton, retryable error and empty state built in. */
export function QueryCard({
  title,
  description,
  action,
  loading,
  error,
  onRetry,
  empty,
  className,
  children,
}: {
  title: string
  description?: ReactNode
  action?: ReactNode
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  /** Rendered instead of `children` when set (an EmptyState). */
  empty?: ReactNode
  className?: string
  children?: ReactNode
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
          <ErrorState compact error={error} onRetry={onRetry} />
        ) : loading ? (
          <div className="space-y-3" role="status" aria-busy="true" aria-label={`Loading ${title}`}>
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-5/6" />
            <Skeleton className="h-6 w-2/3" />
          </div>
        ) : (
          (empty ?? children)
        )}
      </CardContent>
    </Card>
  )
}
