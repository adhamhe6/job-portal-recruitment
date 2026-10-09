import { QueryClientContext } from '@tanstack/react-query'
import { AlertTriangle, Inbox, Loader2, RefreshCw, SearchX, ShieldAlert, WifiOff } from 'lucide-react'
import { useContext, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError, errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * Every async surface needs three states beyond "data": loading (skeletons), empty (EmptyState with a next action)
 * and error (ErrorState with retry). These are the shared building blocks for them.
 */

export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
  compact,
}: {
  title: string
  description?: ReactNode
  /** The useful next step: a Button / Link. */
  action?: ReactNode
  icon?: ReactNode
  className?: string
  compact?: boolean
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 px-6 text-center',
        compact ? 'py-8' : 'py-14',
        className,
      )}
    >
      <div className="mb-1 flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary-soft-foreground [&_svg]:size-6">
        {icon ?? <Inbox aria-hidden />}
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-3 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  )
}

/** Empty state for search/filter results. */
export function NoResults({
  title = 'No results found',
  description,
  action,
}: {
  title?: string
  description?: ReactNode
  action?: ReactNode
}) {
  return <EmptyState title={title} description={description} action={action} icon={<SearchX aria-hidden />} />
}

function describeError(error: unknown): { title: string; message: string; icon: ReactNode } {
  if (error instanceof ApiError) {
    if (error.isNetworkError)
      return {
        title: 'Cannot reach the server',
        message: 'Check your connection and try again.',
        icon: <WifiOff aria-hidden />,
      }
    if (error.status === 403)
      return {
        title: 'Access denied',
        message: 'Your account does not have permission to view this.',
        icon: <ShieldAlert aria-hidden />,
      }
    if (error.status === 404)
      return { title: 'Not found', message: error.message, icon: <SearchX aria-hidden /> }
    if (error.status === 429)
      return { title: 'Slow down a little', message: error.message, icon: <AlertTriangle aria-hidden /> }
    if (error.status >= 500)
      return {
        title: 'Service unavailable',
        message: 'The server hit a problem. Please try again shortly.',
        icon: <AlertTriangle aria-hidden />,
      }
  }
  return { title: 'Something went wrong', message: errorMessage(error), icon: <AlertTriangle aria-hidden /> }
}

/** Retry that also refetches every other failed query on screen (one click recovers a multi-section page). */
export function useRetryFailed(onRetry?: () => void): () => void {
  const client = useContext(QueryClientContext)
  return () => {
    onRetry?.()
    void client?.refetchQueries({ type: 'active', predicate: (q) => q.state.status === 'error' })
  }
}

export function ErrorState({
  error,
  onRetry,
  title,
  className,
  compact,
}: {
  error: unknown
  onRetry?: () => void
  title?: string
  className?: string
  compact?: boolean
}) {
  const d = describeError(error)
  const requestId = error instanceof ApiError ? error.requestId : null
  const retry = useRetryFailed(onRetry)
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center justify-center gap-2 px-6 text-center',
        compact ? 'py-8' : 'py-14',
        className,
      )}
    >
      <div className="mb-1 flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive [&_svg]:size-6">
        {d.icon}
      </div>
      <h3 className="text-base font-semibold">{title ?? d.title}</h3>
      <p className="max-w-md text-sm text-muted-foreground">{d.message}</p>
      {requestId && <p className="text-xs text-muted-foreground">Reference: {requestId}</p>}
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-2" onClick={retry}>
          <RefreshCw /> Try again
        </Button>
      )}
    </div>
  )
}

/** Compact inline error for forms/dialogs. */
export function InlineError({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null
  return (
    <div
      role="alert"
      className={cn(
        'flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive',
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{errorMessage(error)}</span>
    </div>
  )
}

/** Centered spinner for full-page / section loading where a skeleton is not practical. */
export function Spinner({ label = 'Loading', className }: { label?: string; className?: string }) {
  return (
    <div
      role="status"
      className={cn('flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground', className)}
    >
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span>{label}…</span>
    </div>
  )
}

export function TableSkeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-3 p-4" role="status" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-4">
          {Array.from({ length: cols }).map((__, c) => (
            <Skeleton key={c} className={cn('h-5', c === 0 ? 'w-1/3' : 'flex-1')} />
          ))}
        </div>
      ))}
    </div>
  )
}

export function CardGridSkeleton({ count = 4, className }: { count?: number; className?: string }) {
  return (
    <div
      className={cn('grid gap-4 sm:grid-cols-2 xl:grid-cols-4', className)}
      role="status"
      aria-busy="true"
      aria-label="Loading"
    >
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className="h-28 rounded-xl" />
      ))}
    </div>
  )
}
