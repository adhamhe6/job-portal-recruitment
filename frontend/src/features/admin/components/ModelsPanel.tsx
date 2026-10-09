import { Cpu, RefreshCw, Target } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/api'
import { dates, fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import { useEmbeddingsStatus, useMatchingStatus, useRefreshEmbeddings, type Polling } from '../api/admin'
import type { EmbeddingBucket, EmbeddingsStatus, MatchingStatus } from '../api/types'
import { TaskStatusBadge } from './StatusPills'

function Bucket({ title, b }: { title: string; b: EmbeddingBucket }) {
  const pct = b.total === 0 ? 100 : (b.current / b.total) * 100
  const stale = b.outdated + b.missing
  return (
    <li className="space-y-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">
          {fmt.int(b.current)} of {fmt.int(b.total)} up to date
        </p>
      </div>
      <Progress
        value={pct}
        label={`${title}: ${b.current} of ${b.total} embedded with the current model`}
        indicatorClassName={stale > 0 ? 'bg-amber-500' : 'bg-emerald-500'}
      />
      <p className="text-xs text-muted-foreground">
        {b.outdated > 0 && (
          <span className="font-medium text-amber-800 dark:text-amber-300">
            {fmt.int(b.outdated)} outdated ·{' '}
          </span>
        )}
        {b.missing > 0 && (
          <span className="font-medium text-amber-800 dark:text-amber-300">
            {fmt.int(b.missing)} missing ·{' '}
          </span>
        )}
        {stale === 0 ? 'Nothing to refresh.' : b.population}
      </p>
    </li>
  )
}

function EmbeddingsCard({ data }: { data: EmbeddingsStatus }) {
  const refresh = useRefreshEmbeddings()
  const stale = [data.jobs, data.candidates, data.resume_results].reduce(
    (n, b) => n + b.outdated + b.missing,
    0,
  )
  const running = data.active_refresh_task_id !== null

  const run = () =>
    refresh.mutate(undefined, {
      onSuccess: (r) =>
        r.created
          ? toast.success('Re-embedding queued', {
              description: 'Unchanged items are skipped, so this is cheap.',
            })
          : toast.info('A refresh is already queued or running', {
              description: 'No second task was created.',
            }),
      onError: (e) => toast.error('Could not queue the refresh', { description: errorMessage(e) }),
    })

  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between sm:space-y-0">
        <div className="grid gap-1">
          <CardTitle className="flex items-center gap-2 text-base">
            <Cpu className="size-4 text-muted-foreground" aria-hidden /> Embeddings
          </CardTitle>
          <CardDescription>
            {data.model_name} · version {data.model_version} · {fmt.int(data.dimension)} dimensions
          </CardDescription>
        </div>
        <Button onClick={run} loading={refresh.isPending} disabled={running}>
          <RefreshCw /> {running ? 'Re-embedding in progress' : 'Re-embed stale items'}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {stale > 0 && !running && (
          <Alert variant="warning">
            {fmt.int(stale)} item(s) are missing an embedding or use another model version. Re-embed to bring
            them up to date.
          </Alert>
        )}
        <ul className="space-y-4">
          <Bucket title="Published and paused jobs" b={data.jobs} />
          <Bucket title="Candidate profiles" b={data.candidates} />
          <Bucket title="Processed résumés" b={data.resume_results} />
        </ul>
        {data.last_refresh && (
          <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            Last refresh <TaskStatusBadge status={data.last_refresh.status} />
            {data.last_refresh.finished_at && <span>{dates.relative(data.last_refresh.finished_at)}</span>}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function MatchingCard({ data }: { data: MatchingStatus }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Target className="size-4 text-muted-foreground" aria-hidden /> Matching
        </CardTitle>
        <CardDescription>
          Matching version {data.matching_version} · {data.embedding_model} {data.embedding_version}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ['Stored pairs', fmt.int(data.pairs)],
            ['Jobs with matches', `${fmt.int(data.jobs_with_matches)} / ${fmt.int(data.published_jobs)}`],
            ['Candidates with matches', fmt.int(data.candidates_with_matches)],
            ['Match tasks running', fmt.int(data.tasks.active)],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs text-muted-foreground">{k}</dt>
              <dd className="text-xl font-semibold tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
        {data.stale_by_version > 0 && (
          <Alert variant="warning" title="Outdated match scores">
            {fmt.int(data.stale_by_version)} pair(s) were computed with another matching or embedding version.
            Re-embed first, then refresh the matches of the affected jobs from the{' '}
            <Link to={paths.matching} className="font-medium underline">
              Matching page
            </Link>{' '}
            (there is no global match refresh).
          </Alert>
        )}
        {data.published_jobs_without_matches > 0 && (
          <Alert variant="info">
            {fmt.int(data.published_jobs_without_matches)} published job(s) have no matches yet.
          </Alert>
        )}
        {data.by_version.length > 0 && (
          <div>
            <h4 className="mb-1.5 text-sm font-medium">Pairs by version</h4>
            <ul className="divide-y rounded-lg border text-sm">
              {data.by_version.map((v) => (
                <li
                  key={`${v.matching_version}-${v.embedding_model}-${v.embedding_version}`}
                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
                >
                  <span>
                    {v.matching_version} · {v.embedding_model} {v.embedding_version}
                  </span>
                  <span className="flex items-center gap-2">
                    {fmt.int(v.pairs)} pairs
                    <Badge variant={v.current ? 'success' : 'warning'}>
                      {v.current ? 'Current' : 'Outdated'}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-xs text-muted-foreground">
          {data.last_generated_at
            ? `Last match generated ${dates.relative(data.last_generated_at)}.`
            : 'No match has been generated yet.'}
        </p>
      </CardContent>
    </Card>
  )
}

export function ModelsPanel({ polling }: { polling: Polling }) {
  const emb = useEmbeddingsStatus(polling)
  const match = useMatchingStatus(polling)
  const skeleton = (
    <Skeleton className="h-64 rounded-xl" role="status" aria-busy="true" aria-label="Loading" />
  )
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {emb.isError && !emb.data ? (
        <Card>
          <ErrorState error={emb.error} onRetry={() => emb.refetch()} compact />
        </Card>
      ) : emb.data ? (
        <EmbeddingsCard data={emb.data} />
      ) : (
        skeleton
      )}
      {match.isError && !match.data ? (
        <Card>
          <ErrorState error={match.error} onRetry={() => match.refetch()} compact />
        </Card>
      ) : match.data ? (
        <MatchingCard data={match.data} />
      ) : (
        skeleton
      )}
    </div>
  )
}
