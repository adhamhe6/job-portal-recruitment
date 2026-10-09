import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import {
  staffMatchKeys,
  useInvalidateMatches,
  useRefreshJobMatches,
  useTask,
  type RankedCandidatesMeta,
} from '@/features/matches/api/matches'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { ApiError, errorMessage } from '@/lib/api'
import { dates, fmt } from '@/lib/format'
import { pluralize } from '@/lib/utils'

const STAGE_LABELS: Record<string, string> = {
  QUEUED: 'Waiting for a worker',
  LOADING: 'Loading candidates',
  EMBEDDING: 'Reading profiles',
  SCORING: 'Scoring candidates',
  PERSISTING: 'Saving results',
  DONE: 'Done',
}
const stageLabel = (stage: string | null | undefined) =>
  stage ? (STAGE_LABELS[stage.toUpperCase()] ?? fmt.label(stage)) : 'Working'

function refreshErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return 'Too many refreshes in a short time. Please wait a moment and try again.'
    if (e.status === 403) return 'You do not have permission to refresh matches for this job.'
    if (e.status === 409) return e.message
  }
  return errorMessage(e)
}

/**
 * Freshness line + "Refresh matches" button + background-task progress.
 * The task is either one we just queued, or one the API queued itself while serving stale rows (meta.computing_task_id).
 * When it finishes the rankings, job stats and candidate views are invalidated, so the list updates without a reload.
 */
export function RefreshMatchesPanel({
  jobId,
  meta,
}: {
  jobId: string
  meta: RankedCandidatesMeta | undefined
}) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const invalidate = useInvalidateMatches()
  const refresh = useRefreshJobMatches(jobId)
  const [queuedTaskId, setQueuedTaskId] = useState<string | null>(null)
  const taskId = meta?.computing_task_id ?? queuedTaskId
  const task = useTask(taskId)
  const status = task.data?.status
  const handled = useRef<string | null>(null)

  useEffect(() => {
    if (!taskId || !status || (status !== 'COMPLETED' && status !== 'FAILED')) return
    const key = `${taskId}:${status}`
    if (handled.current === key) return
    handled.current = key
    void invalidate(jobId)
    if (status === 'COMPLETED') toast.success('Matches refreshed')
  }, [taskId, status, jobId, invalidate])

  const running = Boolean(taskId) && (task.isPending || status === 'PENDING' || status === 'RUNNING')
  const failed = status === 'FAILED'
  const stale = (meta?.stale_rows ?? 0) > 0

  const start = () => {
    refresh.mutate(undefined, {
      onSuccess: (r) => {
        handled.current = null
        qc.removeQueries({ queryKey: staffMatchKeys.task(r.task_id) })
        setQueuedTaskId(r.task_id)
      },
    })
  }

  return (
    <div className="space-y-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-sm text-muted-foreground">
          {meta
            ? meta.last_generated_at
              ? `${pluralize(meta.total_scored, 'candidate')} scored · last updated ${dates.relative(meta.last_generated_at)}`
              : 'No matches have been computed for this job yet.'
            : 'Checking match freshness…'}
        </p>
        {stale && !running && (
          <span className="rounded-full bg-amber-500/15 px-2.5 py-0.5 text-xs font-medium text-amber-900 dark:text-amber-300">
            {fmt.int(meta?.stale_rows)} out of date
          </span>
        )}
        {can('run_matching') && (
          <Button
            variant="outline"
            size="sm"
            className="sm:ml-auto"
            onClick={start}
            loading={refresh.isPending}
            disabled={running}
          >
            <RefreshCw /> {running ? 'Refreshing…' : 'Refresh matches'}
          </Button>
        )}
      </div>

      {running && (
        <div className="space-y-1.5 rounded-lg border bg-card p-3" role="status">
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="font-medium">{stageLabel(task.data?.stage)}…</span>
            <span className="tabular text-muted-foreground">{task.data?.progress ?? 0}%</span>
          </div>
          <Progress value={task.data?.progress ?? 0} label="Match refresh progress" />
          <p className="text-xs text-muted-foreground">
            You can keep browsing; the ranking updates automatically when this finishes.
          </p>
        </div>
      )}
      {failed && !running && (
        <Alert
          variant="danger"
          title="The match refresh failed"
          action={
            can('run_matching') ? (
              <Button size="sm" variant="outline" onClick={start} loading={refresh.isPending}>
                Try again
              </Button>
            ) : undefined
          }
        >
          {task.data?.error_message ?? 'The background task did not complete.'}
        </Alert>
      )}
      {refresh.isError && <Alert variant="danger">{refreshErrorMessage(refresh.error)}</Alert>}
      {task.isError && !running && !failed && (
        <Alert variant="warning">Couldn’t read the refresh status: {errorMessage(task.error)}</Alert>
      )}
    </div>
  )
}
