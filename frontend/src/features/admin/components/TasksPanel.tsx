import { AlertTriangle, ListChecks, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/common/DataTable'
import { ErrorState } from '@/components/common/States'
import { EmptyState, NoResults } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { SimpleSelect } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError, errorMessage } from '@/lib/api'
import { dates, fmt } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAdminTasks, useRetryTask, type Polling, type TaskFilters } from '../api/admin'
import type { AdminTask, StaleTask, TaskHealth, TaskStatus, TaskType } from '../api/types'
import {
  safeMessage,
  TASK_STATUS_LABELS,
  TASK_STATUS_OPTIONS,
  TASK_STATUS_ORDER,
  TASK_TYPE_OPTIONS,
  taskTypeLabel,
} from '../lib/labels'
import { TaskStatusBadge } from './StatusPills'

const shortId = (id: string) => id.slice(0, 8)

export function describeRetryError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'TASK_NOT_RETRYABLE')
      return 'Only failed tasks can be retried. Its state changed; refresh the list.'
    if (e.code === 'TASK_ALREADY_ACTIVE')
      return 'An equivalent task is already running, so this one was not queued again.'
  }
  return errorMessage(e)
}

function StatusTiles({ health }: { health: TaskHealth | undefined }) {
  if (!health)
    return <Skeleton className="h-24 w-full rounded-xl" role="status" aria-label="Loading task counts" />
  return (
    <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Background tasks by status">
      {TASK_STATUS_ORDER.map((s) => {
        const failed = s === 'FAILED' && (health.by_status[s] ?? 0) > 0
        return (
          <li key={s}>
            <Card className={cn('p-4', failed && 'border-destructive/40')}>
              <p className="text-sm font-medium text-muted-foreground">{TASK_STATUS_LABELS[s]}</p>
              <p className="mt-1 text-2xl font-semibold tracking-tight">
                {fmt.int(health.by_status[s] ?? 0)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {fmt.int(health.last_24h_by_status[s] ?? 0)} in the last 24 h
              </p>
            </Card>
          </li>
        )
      })}
    </ul>
  )
}

function StaleTasks({ health }: { health: TaskHealth }) {
  if (health.stale_count === 0) return null
  const rows: StaleTask[] = health.stale
  return (
    <Alert
      variant="warning"
      title={`${health.stale_count} ${health.stale_count === 1 ? 'task looks' : 'tasks look'} stuck`}
    >
      <p>
        Pending for more than {health.stale_pending_after_minutes} minutes or running without progress for
        more than {health.stale_running_after_minutes} minutes.
        {health.stale_count > rows.length && ` Showing the ${rows.length} oldest.`}
      </p>
      <ul className="mt-2 space-y-1 text-sm">
        {rows.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-medium">{taskTypeLabel(t.type)}</span>
            <TaskStatusBadge status={t.status} />
            <span>{fmt.int(Math.round(t.age_minutes))} min</span>
            {t.stage && <span className="text-muted-foreground">stage: {t.stage}</span>}
            {t.status === 'RUNNING' && t.worker_heartbeat === false && (
              <span className="inline-flex items-center gap-1 font-medium text-destructive">
                <AlertTriangle className="size-3.5" aria-hidden /> worker heartbeat missing
              </span>
            )}
            <span className="font-mono text-xs text-muted-foreground">{shortId(t.id)}</span>
          </li>
        ))}
      </ul>
    </Alert>
  )
}

export function TasksPanel({
  health,
  healthError,
  filters,
  onFilters,
  polling,
}: {
  health: TaskHealth | undefined
  healthError: unknown
  filters: TaskFilters
  onFilters: (patch: Partial<{ tstatus: string; ttype: string; tpage: number }>) => void
  polling: Polling
}) {
  const query = useAdminTasks(filters, polling)
  const retry = useRetryTask()

  const doRetry = (t: AdminTask) =>
    retry.mutate(t.id, {
      onSuccess: () => toast.success(`${taskTypeLabel(t.type)} queued again`),
      onError: (e) => toast.error('Could not retry the task', { description: describeRetryError(e) }),
    })

  const retryButton = (t: AdminTask) =>
    t.status === 'FAILED' ? (
      <Button
        size="sm"
        variant="outline"
        loading={retry.isPending && retry.variables === t.id}
        disabled={retry.isPending}
        onClick={() => doRetry(t)}
        aria-label={`Retry ${taskTypeLabel(t.type)} ${shortId(t.id)}`}
      >
        <RotateCcw /> Retry
      </Button>
    ) : null

  const errorCell = (t: AdminTask) =>
    t.error_code || t.error_message ? (
      <div className="max-w-xs text-xs">
        {t.error_code && <span className="font-mono font-semibold text-destructive">{t.error_code}</span>}
        {t.error_message && (
          <p className="break-words text-muted-foreground" title={safeMessage(t.error_message, 500)}>
            {safeMessage(t.error_message)}
          </p>
        )}
      </div>
    ) : (
      <span className="text-muted-foreground">—</span>
    )

  const columns: Column<AdminTask>[] = [
    {
      key: 'type',
      header: 'Task',
      cell: (t) => (
        <div>
          <p className="font-medium">{taskTypeLabel(t.type)}</p>
          <p className="font-mono text-xs text-muted-foreground">{shortId(t.id)}</p>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (t) => (
        <div className="grid gap-1">
          <TaskStatusBadge status={t.status} />
          {t.stage && <span className="text-xs text-muted-foreground">{t.stage}</span>}
        </div>
      ),
    },
    {
      key: 'progress',
      header: 'Progress',
      hideBelow: 'lg',
      cell: (t) => (
        <div className="flex w-28 items-center gap-2">
          <Progress value={t.progress} label={`Progress of task ${shortId(t.id)}`} className="h-1.5" />
          <span className="text-xs tabular-nums">{t.progress}%</span>
        </div>
      ),
    },
    {
      key: 'attempts',
      header: 'Attempts',
      hideBelow: 'lg',
      align: 'right',
      cell: (t) => fmt.int(t.attempts),
    },
    {
      key: 'created',
      header: 'Created',
      hideBelow: 'md',
      cell: (t) => <span title={dates.dateTime(t.created_at)}>{dates.relative(t.created_at)}</span>,
    },
    { key: 'error', header: 'Error', hideBelow: 'md', cell: (t) => errorCell(t) },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (t) => retryButton(t),
    },
  ]

  const filtered = Boolean(filters.status || filters.type)

  return (
    <div className="space-y-4">
      {healthError && !health ? <ErrorState error={healthError} compact /> : <StatusTiles health={health} />}
      {health && <StaleTasks health={health} />}

      <div className="flex flex-wrap items-center gap-2">
        <SimpleSelect
          aria-label="Filter tasks by status"
          value={filters.status}
          onValueChange={(v) => onFilters({ tstatus: v })}
          options={TASK_STATUS_OPTIONS}
          emptyLabel="Any status"
          className="w-40"
        />
        <SimpleSelect
          aria-label="Filter tasks by type"
          value={filters.type}
          onValueChange={(v) => onFilters({ ttype: v as TaskType | '' })}
          options={TASK_TYPE_OPTIONS}
          emptyLabel="Any type"
          className="w-52"
        />
        {filtered && (
          <Button variant="link" size="sm" onClick={() => onFilters({ tstatus: '', ttype: '' })}>
            Clear filters
          </Button>
        )}
      </div>

      <Card className="overflow-hidden p-0">
        <DataTable
          caption="Background tasks, newest first"
          rows={query.data?.items}
          rowKey={(t) => t.id}
          columns={columns}
          loading={query.isFetching && !query.data}
          error={query.isError && !query.data ? query.error : undefined}
          onRetry={() => query.refetch()}
          page={query.data?.page}
          pages={query.data?.pages}
          total={query.data?.total}
          pageSize={filters.pageSize}
          onPageChange={(p) => onFilters({ tpage: p })}
          renderCard={(t) => (
            <div className="space-y-2 p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{taskTypeLabel(t.type)}</p>
                  <p className="font-mono text-xs text-muted-foreground">{shortId(t.id)}</p>
                </div>
                <TaskStatusBadge status={t.status as TaskStatus} />
              </div>
              <p className="text-xs text-muted-foreground">
                {t.stage ? `${t.stage} · ` : ''}
                {t.progress}% · {t.attempts} attempt(s) · {dates.relative(t.created_at)}
              </p>
              {errorCell(t)}
              {retryButton(t)}
            </div>
          )}
          empty={
            filtered ? (
              <NoResults title="No tasks match these filters" />
            ) : (
              <EmptyState
                icon={<ListChecks aria-hidden />}
                title="No background tasks yet"
                description="Tasks appear here when résumés are processed or matches are computed."
              />
            )
          }
        />
      </Card>
    </div>
  )
}
