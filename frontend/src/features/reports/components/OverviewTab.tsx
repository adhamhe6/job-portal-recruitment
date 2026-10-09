import { CheckCircle2, ClipboardList, Hourglass, Layers } from 'lucide-react'
import { ChartCard } from '@/components/common/ChartCard'
import { KpiCard } from '@/components/common/KpiCard'
import { EmptyState } from '@/components/common/States'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { fmt } from '@/lib/format'
import { pluralize } from '@/lib/utils'
import { useFunnel, usePipelineSummary, useStatusBreakdown } from '../api/reports'
import type { ReportFilters } from '../api/types'
import { HBarChart, SimpleTable } from './charts'
import { QueryCard } from './QueryCard'

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${fmt.num(v)}%`)

export function OverviewTab({ filters }: { filters: ReportFilters }) {
  const funnel = useFunnel(filters)
  const status = useStatusBreakdown(filters)
  const pipeline = usePipelineSummary(filters)

  const main = funnel.data?.stages.filter((s) => !s.is_branch) ?? []
  const branches = funnel.data?.stages.filter((s) => s.is_branch) ?? []
  const hired = main.find((s) => s.stage === 'HIRED')
  const funnelData = main.map((s) => ({
    label: APPLICATION_STATUS_LABELS[s.stage],
    value: s.count,
    text: `${fmt.int(s.count)} · ${pct(s.pct_of_applied)}`,
  }))
  const noApplications = funnel.data?.applications === 0

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Applications"
          value={fmt.int(funnel.data?.applications)}
          icon={<ClipboardList />}
          hint={filters.from || filters.to ? 'Received in the selected period' : 'All time'}
          loading={funnel.isPending}
        />
        <KpiCard
          label="Hired"
          value={fmt.int(hired?.count)}
          icon={<CheckCircle2 />}
          tone="success"
          hint={hired ? `${pct(hired.pct_of_applied)} of applications` : undefined}
          loading={funnel.isPending}
        />
        <KpiCard
          label="Active in pipeline"
          value={fmt.int(pipeline.data?.live)}
          icon={<Layers />}
          tone="info"
          hint="Current snapshot"
          loading={pipeline.isPending}
        />
        <KpiCard
          label="Waiting too long"
          value={fmt.int(pipeline.data?.stale)}
          icon={<Hourglass />}
          tone={pipeline.data && pipeline.data.stale > 0 ? 'warning' : 'default'}
          hint={pipeline.data ? `No change for over ${pipeline.data.stale_after_days} days` : undefined}
          loading={pipeline.isPending}
        />
      </div>
      {(funnel.isError || pipeline.isError) && (
        <p className="sr-only" role="status">
          Some figures could not be loaded.
        </p>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <ChartCard
          title="Hiring funnel"
          description="Applications that ever reached each stage, with their share of all applications"
          loading={funnel.isPending}
          error={funnel.isError ? funnel.error : undefined}
          onRetry={() => funnel.refetch()}
          height={300}
          srSummary={funnelData.map((d) => `${d.label}: ${d.text}`).join('; ')}
        >
          {noApplications ? (
            <EmptyState
              compact
              title="No applications in this period"
              description="Widen the date range or pick a different job."
            />
          ) : (
            <HBarChart data={funnelData} name="Applications" rightMargin={84} labelWidth={92} />
          )}
        </ChartCard>

        <QueryCard
          title="Stage conversion"
          description={
            branches.length
              ? `Also: ${branches.map((b) => `${APPLICATION_STATUS_LABELS[b.stage].toLowerCase()} ${b.count}`).join(', ')}`
              : 'Share of applicants moving on from the previous stage'
          }
          loading={funnel.isPending}
          error={funnel.isError ? funnel.error : undefined}
          onRetry={() => funnel.refetch()}
          empty={noApplications ? <EmptyState compact title="Nothing to convert yet" /> : undefined}
        >
          <SimpleTable
            caption="Hiring funnel by stage"
            rows={funnel.data?.stages ?? []}
            rowKey={(s) => s.stage}
            columns={[
              { key: 'stage', header: 'Stage', cell: (s) => APPLICATION_STATUS_LABELS[s.stage] },
              { key: 'count', header: 'Reached', align: 'right', cell: (s) => fmt.int(s.count) },
              { key: 'applied', header: '% of applied', align: 'right', cell: (s) => pct(s.pct_of_applied) },
              {
                key: 'prev',
                header: 'From previous stage',
                align: 'right',
                cell: (s) => (s.is_branch ? 'Branch' : pct(s.pct_of_previous)),
              },
            ]}
            className="border-0 shadow-none"
          />
        </QueryCard>
      </div>

      <ChartCard
        title="Applications by current status"
        description={
          status.data ? `${pluralize(status.data.total, 'application')} in the selected scope` : undefined
        }
        loading={status.isPending}
        error={status.isError ? status.error : undefined}
        onRetry={() => status.refetch()}
        height={300}
        srSummary={status.data?.items
          .map((i) => `${APPLICATION_STATUS_LABELS[i.status]}: ${i.count}`)
          .join('; ')}
      >
        <HBarChart
          data={(status.data?.items ?? []).map((i) => ({
            label: APPLICATION_STATUS_LABELS[i.status],
            value: i.count,
            text: `${fmt.int(i.count)} · ${pct(i.percent)}`,
          }))}
          name="Applications"
          rightMargin={84}
          labelWidth={92}
        />
      </ChartCard>
      {status.data && (
        <SimpleTable
          srOnly
          caption="Applications by current status"
          rows={status.data.items}
          rowKey={(i) => i.status}
          columns={[
            { key: 's', header: 'Status', cell: (i) => APPLICATION_STATUS_LABELS[i.status] },
            { key: 'c', header: 'Applications', align: 'right', cell: (i) => i.count },
            { key: 'p', header: 'Share', align: 'right', cell: (i) => pct(i.percent) },
          ]}
        />
      )}
    </div>
  )
}
