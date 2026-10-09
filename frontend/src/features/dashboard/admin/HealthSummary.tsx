import { CheckCircle2, ChevronRight, XCircle, AlertTriangle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ErrorState } from '@/components/common/States'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useMatchingStatus, useSystemStatus } from '@/features/admin/api/admin'
import { TASK_STATUS_LABELS, TASK_STATUS_ORDER } from '@/features/admin/lib/labels'
import { fmt } from '@/lib/format'
import { paths } from '@/routes/paths'

function Pill({ ok, label, detail }: { ok: boolean | null; label: string; detail: string }) {
  const Icon = ok === null ? AlertTriangle : ok ? CheckCircle2 : XCircle
  return (
    <li className="flex items-center justify-between gap-3 py-2 text-sm">
      <span className="flex items-center gap-2">
        <Icon
          className={
            ok === null
              ? 'size-4 text-amber-600 dark:text-amber-400'
              : ok
                ? 'size-4 text-emerald-600 dark:text-emerald-400'
                : 'size-4 text-red-600 dark:text-red-400'
          }
          aria-hidden
        />
        {label}
      </span>
      <span className="text-muted-foreground">{detail}</span>
    </li>
  )
}

/** Dependency, background-task and matching health at a glance, linking to the monitoring console. */
export function HealthSummary() {
  const system = useSystemStatus()
  const matching = useMatchingStatus()
  const d = system.data

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-base">System health</CardTitle>
        {d && (
          <Badge variant={d.status === 'ok' ? 'success' : d.status === 'degraded' ? 'warning' : 'danger'}>
            {d.status === 'ok' ? 'Operational' : d.status === 'degraded' ? 'Degraded' : 'Down'}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {system.isError ? (
          <ErrorState error={system.error} onRetry={() => system.refetch()} compact />
        ) : !d ? (
          <div className="space-y-2" role="status" aria-busy="true" aria-label="Loading system health">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : (
          <>
            <ul className="divide-y" aria-label="Dependencies">
              <Pill
                ok={d.database.ok}
                label="Database"
                detail={d.database.ok ? `${fmt.num(d.database.latency_ms)} ms` : 'Unreachable'}
              />
              <Pill
                ok={d.redis.ok}
                label="Redis"
                detail={d.redis.ok ? `queue ${fmt.int(d.redis.queue_depth)}` : 'Unreachable'}
              />
              <Pill
                ok={d.worker.alive}
                label="Worker"
                detail={
                  d.worker.alive === null ? 'Runs in the API' : d.worker.alive ? 'Alive' : 'Not responding'
                }
              />
              <Pill
                ok={d.embedding.loaded}
                label="Embedding model"
                detail={d.embedding.loaded ? d.embedding.model_name : 'Not loaded'}
              />
            </ul>
            <div>
              <h3 className="mb-1.5 text-sm font-medium">Background tasks, last 24 h</h3>
              <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="Tasks by status">
                {TASK_STATUS_ORDER.map((s) => (
                  <li
                    key={s}
                    className={
                      s === 'FAILED' && (d.tasks.last_24h_by_status[s] ?? 0) > 0
                        ? 'font-semibold text-destructive'
                        : ''
                    }
                  >
                    {TASK_STATUS_LABELS[s]}:{' '}
                    <span className="tabular-nums">{fmt.int(d.tasks.last_24h_by_status[s] ?? 0)}</span>
                  </li>
                ))}
              </ul>
              {d.tasks.stale_count > 0 && (
                <p className="mt-1.5 text-sm font-medium text-amber-800 dark:text-amber-300">
                  {d.tasks.stale_count} stuck task(s) need attention.
                </p>
              )}
            </div>
            {matching.data && (
              <p className="text-sm text-muted-foreground">
                Matching: {fmt.int(matching.data.pairs)} pairs
                {matching.data.stale_by_version > 0
                  ? `, ${fmt.int(matching.data.stale_by_version)} outdated`
                  : ', all current'}
                {matching.data.published_jobs_without_matches > 0 &&
                  `, ${fmt.int(matching.data.published_jobs_without_matches)} job(s) without matches`}
                .
              </p>
            )}
          </>
        )}
        <Link
          to={paths.adminSystem}
          className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          Open system monitoring <ChevronRight className="size-4" aria-hidden />
        </Link>
      </CardContent>
    </Card>
  )
}
