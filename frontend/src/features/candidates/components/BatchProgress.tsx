import { CheckCircle2, CircleDashed, Copy, Loader2, RefreshCw, XCircle } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { ErrorState } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/api'
import { dates, fmt } from '@/lib/format'
import { pluralize } from '@/lib/utils'
import { paths } from '@/routes/paths'
import {
  isBatchActive,
  useBulkImportBatch,
  useInvalidateCandidates,
  useReprocessBatch,
  type BulkImportItem,
  type ImportItemStatus,
} from '../api/bulkImport'
import { formatBytes, ITEM_REASONS } from '../lib/bulkImport'

const ITEM_STATUS: Record<ImportItemStatus, { label: string; icon: typeof Loader2; tone: string }> = {
  PENDING: { label: 'Waiting', icon: CircleDashed, tone: 'text-muted-foreground' },
  CREATED: { label: 'Imported', icon: CheckCircle2, tone: 'text-emerald-700 dark:text-emerald-400' },
  DUPLICATE: { label: 'Duplicate', icon: Copy, tone: 'text-amber-700 dark:text-amber-400' },
  FAILED: { label: 'Failed', icon: XCircle, tone: 'text-destructive' },
}

function ItemRow({ item }: { item: BulkImportItem }) {
  const s = ITEM_STATUS[item.status] ?? ITEM_STATUS.PENDING
  const Icon = s.icon
  const reason =
    item.status === 'CREATED' || item.status === 'PENDING'
      ? null
      : (item.error_message ?? (item.error_code ? ITEM_REASONS[item.error_code] : null) ?? item.error_code)
  return (
    <li className="flex items-start gap-3 py-2.5">
      <Icon className={`mt-0.5 size-4 shrink-0 ${s.tone}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={item.filename}>
          {item.filename}
        </p>
        <p className="text-xs text-muted-foreground">
          <span className={`font-medium ${s.tone}`}>{s.label}</span> · {formatBytes(item.size_bytes)}
          {reason && <> · {reason}</>}
        </p>
      </div>
      {item.candidate_id && (
        <Link
          to={paths.candidate(item.candidate_id)}
          className="shrink-0 rounded-sm text-sm font-medium text-primary hover:underline"
        >
          {item.status === 'DUPLICATE' ? 'View existing' : 'View profile'}
          <span className="sr-only"> for {item.filename}</span>
        </Link>
      )}
    </li>
  )
}

/**
 * Live status of one import batch: overall progress, counts per outcome and one row per file with its success/failure
 * reason. Polls GET /resumes/bulk-imports/{id} until the background task finishes, then refreshes candidate searches.
 */
export function BatchProgress({ batchId, title }: { batchId: string; title?: string }) {
  const batch = useBulkImportBatch(batchId)
  const reprocess = useReprocessBatch()
  const invalidateCandidates = useInvalidateCandidates()
  const data = batch.data
  const active = isBatchActive(data)
  const finishedRef = useRef(false)

  useEffect(() => {
    if (data && !isBatchActive(data) && !finishedRef.current) {
      finishedRef.current = true
      void invalidateCandidates()
    }
    if (data && isBatchActive(data)) finishedRef.current = false
  }, [data, invalidateCandidates])

  if (batch.isPending)
    return (
      <div className="space-y-2" role="status" aria-busy="true" aria-label="Loading import status">
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-2 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    )
  if (batch.isError && !data)
    return (
      <ErrorState
        compact
        error={batch.error}
        onRetry={() => batch.refetch()}
        title="Couldn't load this import"
      />
    )
  if (!data) return null

  const done = data.counts.created + data.counts.duplicate + data.counts.failed
  const pct =
    data.status === 'COMPLETED'
      ? 100
      : (data.progress ?? Math.round((done / Math.max(1, data.total_files)) * 100))
  // The queue was down at upload time (or a worker was lost): nothing will move until it is re-queued.
  const stuck = active && !data.task_id

  return (
    <section aria-label={title ?? 'Import batch'} className="space-y-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">
          {title ?? 'Import'}{' '}
          <span className="font-normal text-muted-foreground">
            · {fmt.int(data.total_files)} {pluralize(data.total_files, 'file')} ·{' '}
            {dates.relative(data.created_at)}
          </span>
        </h3>
        <span role="status" className="text-sm font-medium">
          {active ? (
            <span className="inline-flex items-center gap-1.5 text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> Processing… {pct}%
            </span>
          ) : data.status === 'FAILED' ? (
            <span className="text-destructive">Import failed</span>
          ) : (
            <span className="text-emerald-700 dark:text-emerald-400">Finished</span>
          )}
        </span>
      </div>
      <Progress value={pct} label="Import progress" />
      <p className="text-sm text-muted-foreground">
        {fmt.int(data.counts.created)} imported · {fmt.int(data.counts.duplicate)} duplicate
        {data.counts.duplicate === 1 ? '' : 's'} · {fmt.int(data.counts.failed)} failed
        {data.counts.pending > 0 && <> · {fmt.int(data.counts.pending)} waiting</>}
      </p>

      {stuck && (
        <Alert
          variant="warning"
          title="Processing has not started"
          action={
            <Button
              size="sm"
              variant="outline"
              onClick={() => reprocess.mutate(batchId)}
              loading={reprocess.isPending}
            >
              <RefreshCw /> Retry processing
            </Button>
          }
        >
          The background queue was unavailable when these files were uploaded. Retry to process them now.
        </Alert>
      )}
      {reprocess.isError && <Alert variant="danger">{errorMessage(reprocess.error)}</Alert>}
      {batch.isError && data && (
        <Alert variant="warning">Couldn’t refresh the status just now; showing the last known state.</Alert>
      )}

      {data.items.length > 0 && (
        <ul
          className="max-h-72 divide-y overflow-y-auto rounded-lg border px-3"
          aria-label="Files in this import"
        >
          {data.items.map((it) => (
            <ItemRow key={it.id} item={it} />
          ))}
        </ul>
      )}
    </section>
  )
}
