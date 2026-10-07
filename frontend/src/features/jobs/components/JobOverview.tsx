import { ClipboardList, Clock, Target } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts'
import { ChartCard, chartTheme } from '@/components/common/ChartCard'
import { KpiCard } from '@/components/common/KpiCard'
import { useJobStats } from '../api/jobs'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { dates, fmt } from '@/lib/format'
import type { ApplicationStatus } from '@/lib/api'

const PIPELINE: ApplicationStatus[] = ['APPLIED', 'SCREENING', 'SHORTLISTED', 'INTERVIEW', 'OFFER', 'HIRED', 'REJECTED', 'WITHDRAWN']

/** Staff-only overview: GET /jobs/{id}/stats -> KPIs + applications-by-status chart (pipeline order, zeros included). */
export function JobOverview({ jobId }: { jobId: string }) {
  const stats = useJobStats(jobId)
  const by = stats.data?.applications_by_status ?? {}
  const rows = PIPELINE.map((s) => ({ status: APPLICATION_STATUS_LABELS[s], value: by[s] ?? 0 }))
  const total = stats.data?.applications_total ?? 0
  const summary = rows.map((r) => `${r.status}: ${r.value}`).join(', ')

  return (
    <section aria-labelledby="overview-heading" className="space-y-4">
      <h2 id="overview-heading" className="text-lg font-semibold tracking-tight">
        Overview
      </h2>
      <div className="grid gap-4 sm:grid-cols-3">
        <KpiCard label="Applications" value={fmt.int(total)} icon={<ClipboardList />} loading={stats.isPending} />
        <KpiCard label="Matches computed" value={fmt.int(stats.data?.matches_computed)} icon={<Target />} tone="info" loading={stats.isPending} />
        <KpiCard
          label="Last matched"
          value={stats.data?.last_matched_at ? dates.relative(stats.data.last_matched_at) : 'Not yet'}
          icon={<Clock />}
          tone="warning"
          loading={stats.isPending}
          className="[&_p.text-3xl]:text-2xl"
        />
      </div>
      <ChartCard
        title="Applications by status"
        description={total === 0 ? 'No applications yet' : `${fmt.int(total)} application${total === 1 ? '' : 's'} across the hiring pipeline`}
        loading={stats.isPending}
        error={stats.isError ? stats.error : undefined}
        onRetry={() => stats.refetch()}
        height={280}
        srSummary={summary}
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 36, bottom: 4, left: 4 }} barCategoryGap={10}>
            <CartesianGrid horizontal={false} stroke={chartTheme.grid} strokeWidth={1} />
            <XAxis type="number" allowDecimals={false} tick={chartTheme.axis} tickLine={false} axisLine={false} domain={[0, (max: number) => Math.max(4, max)]} />
            <YAxis type="category" dataKey="status" width={92} tick={chartTheme.axis} tickLine={false} axisLine={false} />
            <ChartTooltip cursor={chartTheme.tooltip.cursor} contentStyle={chartTheme.tooltip.contentStyle} labelStyle={chartTheme.tooltip.labelStyle} formatter={(v) => [fmt.int(v as number), 'Applications']} />
            <Bar dataKey="value" name="Applications" fill="var(--chart-1)" barSize={18} radius={[0, 4, 4, 0]} isAnimationActive={false}>
              <LabelList dataKey="value" position="right" fill="var(--foreground)" fontSize={12} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>
      <table className="sr-only">
        <caption>Applications by status</caption>
        <thead>
          <tr>
            <th scope="col">Status</th>
            <th scope="col">Applications</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.status}>
              <th scope="row">{r.status}</th>
              <td>{r.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
