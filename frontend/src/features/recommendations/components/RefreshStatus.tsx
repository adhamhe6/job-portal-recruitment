import { Loader2 } from 'lucide-react'
import { Alert } from '@/components/ui/alert'
import { Progress } from '@/components/ui/progress'
import { fmt } from '@/lib/format'
import type { TaskOut } from '@/features/tasks/api/tasks'

/** Progress / outcome of the background recompute. Renders nothing when idle. */
export function RefreshStatus({
  task,
  queued,
  error,
}: {
  task: TaskOut | undefined
  /** The request was accepted but the task has not been read yet. */
  queued: boolean
  error: string | null
}) {
  if (error)
    return (
      <Alert variant="danger" title="Couldn't refresh your recommendations">
        {error}
      </Alert>
    )
  if (task?.status === 'FAILED')
    return (
      <Alert variant="danger" title="Refreshing your recommendations failed">
        {task.error_message ?? 'The background task did not finish.'} Your previous recommendations are still
        shown. Try again in a moment.
      </Alert>
    )
  const running = queued || task?.status === 'PENDING' || task?.status === 'RUNNING'
  if (!running) return null
  const pct = task?.progress ?? 0
  return (
    <div className="mb-4 rounded-xl border bg-card p-4" role="status" aria-live="polite">
      <p className="flex items-center gap-2 text-sm font-medium">
        <Loader2 className="size-4 animate-spin text-primary" aria-hidden />
        Refreshing your recommendations…
      </p>
      <Progress className="mt-3" value={pct} label="Recommendation refresh progress" />
      <p className="mt-1.5 text-xs text-muted-foreground">
        {task?.stage ? `${fmt.label(task.stage)} · ` : task?.status === 'PENDING' ? 'Queued · ' : ''}
        {Math.round(pct)}%
      </p>
    </div>
  )
}
