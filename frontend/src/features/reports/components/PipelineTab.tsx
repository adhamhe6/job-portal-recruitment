import { Clock } from 'lucide-react'
import { ChartCard } from '@/components/common/ChartCard'
import { KpiCard } from '@/components/common/KpiCard'
import { EmptyState } from '@/components/common/States'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { fmt } from '@/lib/format'
import { useJobPerformance, usePipelineSummary } from '../api/reports'
import type { ReportFilters } from '../api/types'
import { HBarChart, SimpleTable } from './charts'
import { QueryCard } from './QueryCard'

const LIVE_STAGES = ['APPLIED', 'SCREENING', 'SHORTLISTED', 'INTERVIEW', 'OFFER']
const days = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${fmt.num(v)} d`)

/** Applicant-weighted average days to hire across the listed jobs (null when nobody was hired). */
export function weightedDaysToHire(rows: { hires: number; avg_days_to_hire: number | null }[]): number | null {
  let hires = 0
  let total = 0
  for (const r of rows) {
    if (r.avg_days_to_hire === null || r.hires <= 0) continue
    hires += r.hires
    total += r.avg_days_to_hire * r.hires
  }
  return hires > 0 ? total / hires : null
}

export function PipelineTab({ filters }: { filters: ReportFilters }) {
  const pipeline = usePipelineSummary(filters)
  // One request for "all jobs" (max 100 per page) is enough for the time-to-hire chart; jobs without hires drop out.
  const perf = useJobPerformance(filters, { page: 1, pageSize: 100, sort: 'hire_rate', order: 'desc' })

  const live = (pipeline.data?.stages ?? []).filter((s) => LIVE_STAGES.includes(s.stage))
  const stageData = live.map((s) => ({
    label: APPLICATION_STATUS_LABELS[s.stage],
    value: s.avg_days_in_stage ?? 0,
    text: s.count ? `${fmt.num(s.avg_days_in_stage)} d · ${s.count}` : 'none',
  }))
  const hiredJobs = (perf.data?.items ?? [])
    .filter((r) => r.avg_days_to_hire !== null)
    .sort((a, b) => (b.avg_days_to_hire ?? 0) - (a.avg_days_to_hire ?? 0))
    .slice(0, 12)
  const complete = (perf.data?.pages ?? 1) <= 1
  const overall = perf.data && complete ? weightedDaysToHire(perf.data.items) : null

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <KpiCard
          label="Avg. days to hire"
          value={overall === null ? '—' : `${fmt.num(overall)} d`}
          icon={<Clock />}
          hint={
            overall === null
              ? perf.data && !complete
                ? 'More than 100 jobs: see the Jobs tab'
                : 'No hires in this period'
              : 'From application to hire, weighted by hires'
          }
          loading={perf.isPending}
        />
        <KpiCard
          label="Active in pipeline"
          value={fmt.int(pipeline.data?.live)}
          tone="info"
          hint={filters.jobId ? 'For the selected job' : 'All jobs, current snapshot'}
          loading={pipeline.isPending}
        />
        <KpiCard
          label={`Stale (over ${pipeline.data?.stale_after_days ?? 14} days)`}
          value={fmt.int(pipeline.data?.stale)}
          tone={pipeline.data && pipeline.data.stale > 0 ? 'warning' : 'default'}
          hint="Live applications with no stage change"
          loading={pipeline.isPending}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <ChartCard
          title="Time in current stage"
          description="Average days live applications have been waiting in each stage (snapshot; the date range does not apply)"
          loading={pipeline.isPending}
          error={pipeline.isError ? pipeline.error : undefined}
          onRetry={() => pipeline.refetch()}
          height={280}
          srSummary={live
            .map((s) => `${APPLICATION_STATUS_LABELS[s.stage]}: ${s.count} applications, average ${s.avg_days_in_stage ?? 'n/a'} days`)
            .join('; ')}
        >
          {pipeline.data && pipeline.data.live === 0 ? (
            <EmptyState compact title="No live applications" description="Nothing is waiting in the pipeline right now." />
          ) : (
            <HBarChart data={stageData} name="Average days in stage" format={(v) => `${fmt.num(v)} d`} rightMargin={84} labelWidth={92} />
          )}
        </ChartCard>

        <ChartCard
          title="Days to hire by job"
          description="Average days from application to hire, jobs with at least one hire"
          loading={perf.isPending}
          error={perf.isError ? perf.error : undefined}
          onRetry={() => perf.refetch()}
          height={280}
          srSummary={hiredJobs.map((r) => `${r.title}: ${r.avg_days_to_hire} days (${r.hires} hires)`).join('; ')}
        >
          {hiredJobs.length === 0 ? (
            <EmptyState
              compact
              title="No hires yet"
              description="Time to hire appears once candidates are hired in the selected period."
            />
          ) : (
            <HBarChart
              data={hiredJobs.map((r) => ({ label: r.title, value: r.avg_days_to_hire ?? 0 }))}
              name="Average days to hire"
              format={(v) => `${fmt.num(v)} d`}
              labelWidth={120}
              color="var(--chart-3)"
            />
          )}
        </ChartCard>
      </div>

      <QueryCard
        title="Stage details"
        description="How long applications have been in their current stage"
        loading={pipeline.isPending}
        error={pipeline.isError ? pipeline.error : undefined}
        onRetry={() => pipeline.refetch()}
      >
        <SimpleTable
          caption="Applications and time in stage"
          rows={pipeline.data?.stages ?? []}
          rowKey={(s) => s.stage}
          className="border-0 shadow-none"
          columns={[
            { key: 'stage', header: 'Stage', cell: (s) => APPLICATION_STATUS_LABELS[s.stage] },
            { key: 'count', header: 'Applications', align: 'right', cell: (s) => fmt.int(s.count) },
            { key: 'avg', header: 'Avg. in stage', align: 'right', cell: (s) => days(s.avg_days_in_stage) },
            { key: 'max', header: 'Longest', align: 'right', cell: (s) => days(s.max_days_in_stage) },
            { key: 'stale', header: 'Stale', align: 'right', cell: (s) => fmt.int(s.stale) },
          ]}
        />
      </QueryCard>
    </div>
  )
}
