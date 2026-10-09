import { CheckCircle2, Cpu, Database, HardDrive, Layers, Server, XCircle, AlertTriangle } from 'lucide-react'
import type { ReactNode } from 'react'
import { ErrorState } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { dates, fmt } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { SystemStatus } from '../api/types'
import { safeMessage } from '../lib/labels'

type Tone = 'ok' | 'warn' | 'bad' | 'unknown'
const TONE_BADGE = { ok: 'success', warn: 'warning', bad: 'danger', unknown: 'muted' } as const
const TONE_ICON = { ok: CheckCircle2, warn: AlertTriangle, bad: XCircle, unknown: AlertTriangle } as const

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right font-medium break-words">{children}</dd>
    </div>
  )
}

function DependencyCard({
  title,
  icon,
  tone,
  label,
  children,
  error,
}: {
  title: string
  icon: ReactNode
  tone: Tone
  label: string
  children: ReactNode
  error?: string | null
}) {
  const Icon = TONE_ICON[tone]
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-base [&_svg]:size-4 [&_svg]:text-muted-foreground">
          {icon}
          {title}
        </CardTitle>
        <Badge variant={TONE_BADGE[tone]} className="gap-1">
          <Icon aria-hidden />
          {label}
        </Badge>
      </CardHeader>
      <CardContent>
        <dl className="divide-y">{children}</dl>
        {error && (
          <p
            role="alert"
            className="mt-2 rounded-md bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive"
          >
            {safeMessage(error)}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

const ms = (v: number | null) => (v === null ? '—' : `${fmt.num(v)} ms`)

const OVERALL = {
  ok: { variant: 'success', title: 'All systems operational' },
  degraded: { variant: 'warning', title: 'Degraded: something needs attention' },
  down: { variant: 'danger', title: 'Down: the database is unreachable' },
} as const

export function HealthPanel({
  data,
  isPending,
  error,
  onRetry,
}: {
  data: SystemStatus | undefined
  isPending: boolean
  error: unknown
  onRetry: () => void
}) {
  if (error && !data) return <ErrorState error={error} onRetry={onRetry} />
  if (isPending || !data)
    return (
      <div
        className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
        role="status"
        aria-busy="true"
        aria-label="Loading system health"
      >
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-44 rounded-xl" />
        ))}
      </div>
    )

  const { database: db, redis, worker, embedding: emb, app } = data
  const overall = OVERALL[data.status]
  const dbTone: Tone = !db.ok ? 'bad' : db.migrations_current === false ? 'warn' : 'ok'
  const workerTone: Tone =
    worker.alive === null ? 'unknown' : worker.alive ? ((worker.jobs_failed ?? 0) > 0 ? 'warn' : 'ok') : 'bad'

  return (
    <div className="space-y-4">
      <Alert variant={overall.variant} title={overall.title}>
        Checked {dates.relative(data.checked_at)} ({dates.dateTime(data.checked_at)}).
        {data.tasks.stale_count > 0 && ` ${data.tasks.stale_count} background task(s) look stuck.`}
      </Alert>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <DependencyCard
          title="Database"
          icon={<Database aria-hidden />}
          tone={dbTone}
          label={!db.ok ? 'Unreachable' : db.migrations_current === false ? 'Migrations behind' : 'Healthy'}
          error={db.error}
        >
          <Row label="Latency">{ms(db.latency_ms)}</Row>
          <Row label="pgvector">{db.pgvector_version ?? 'Not installed'}</Row>
          <Row label="Migration">
            {db.migration_revision ?? 'Unknown'}
            {db.migration_head &&
              db.migration_head !== db.migration_revision &&
              ` (head ${db.migration_head})`}
          </Row>
        </DependencyCard>

        <DependencyCard
          title="Redis"
          icon={<HardDrive aria-hidden />}
          tone={redis.ok ? 'ok' : 'bad'}
          label={redis.ok ? 'Healthy' : 'Unreachable'}
          error={redis.error}
        >
          <Row label="Latency">{ms(redis.latency_ms)}</Row>
          <Row label="Queue depth">{redis.queue_depth === null ? '—' : fmt.int(redis.queue_depth)}</Row>
          <Row label="Cache">{app.cache_enabled ? 'Enabled' : 'Disabled'}</Row>
        </DependencyCard>

        <DependencyCard
          title="Worker"
          icon={<Server aria-hidden />}
          tone={workerTone}
          label={worker.alive === null ? 'Runs in the API' : worker.alive ? 'Alive' : 'Not responding'}
        >
          <Row label="Mode">
            {worker.mode === 'arq' ? 'Separate worker (ARQ)' : 'Inline (in the API process)'}
          </Row>
          {worker.health_ttl_seconds !== null && (
            <Row label="Heartbeat expires in">{fmt.num(worker.health_ttl_seconds)} s</Row>
          )}
          <Row label="Jobs">
            {fmt.int(worker.jobs_complete)} done · {fmt.int(worker.jobs_failed)} failed ·{' '}
            {fmt.int(worker.jobs_retried)} retried
          </Row>
          <Row label="Running / queued">
            {fmt.int(worker.jobs_ongoing)} / {fmt.int(worker.queued)}
          </Row>
          {worker.last_check && (
            <p className="pt-2 font-mono text-[11px] break-words text-muted-foreground">
              {safeMessage(worker.last_check)}
            </p>
          )}
        </DependencyCard>

        <DependencyCard
          title="Embedding model"
          icon={<Cpu aria-hidden />}
          tone={emb.loaded ? 'ok' : 'bad'}
          label={emb.loaded ? 'Loaded' : 'Not loaded'}
          error={emb.error}
        >
          <Row label="Model">{emb.model_name}</Row>
          <Row label="Version">{emb.model_version}</Row>
          <Row label="Backend">{emb.backend}</Row>
          <Row label="Dimensions">{fmt.int(emb.dimension)}</Row>
        </DependencyCard>

        <DependencyCard title="Application" icon={<Layers aria-hidden />} tone="ok" label={app.environment}>
          <Row label="Name">
            {app.name} {app.version}
          </Row>
          <Row label="Python">{app.python_version}</Row>
          <Row label="Background jobs">{app.job_backend}</Row>
        </DependencyCard>
      </div>
      <p className={cn('text-xs text-muted-foreground')}>
        Rate-limit counters are enforced by the API but are not exposed to the console, so only cache
        availability is shown.
      </p>
    </div>
  )
}
