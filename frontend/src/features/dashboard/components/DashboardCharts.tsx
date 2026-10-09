import { format, parseISO } from 'date-fns'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChartCard, chartTheme } from '@/components/common/ChartCard'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { fmt } from '@/lib/format'
import type { RecruiterDashboardData } from '../api/dashboard'

type Query = { isPending: boolean; error: unknown; refetch: () => unknown }

const bucketLabel = (b: string, granularity: string | null) =>
  format(parseISO(b), granularity === 'month' ? 'MMM yyyy' : 'MMM d')

/** Applications by current status (pipeline order, zeros included) and applications over time. Lazy-loaded with Recharts. */
export default function DashboardCharts({
  data,
  query,
}: {
  data: RecruiterDashboardData | undefined
  query: Query
}) {
  const status = (data?.status_distribution ?? []).map((s) => ({
    label: APPLICATION_STATUS_LABELS[s.status],
    value: s.count,
  }))
  const series = (data?.applications_over_time ?? []).map((p) => ({
    label: bucketLabel(p.bucket, data?.period.granularity ?? 'day'),
    value: p.count,
  }))
  const totalSeries = series.reduce((n, p) => n + p.value, 0)
  const loading = query.isPending
  const error = query.error ?? undefined

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard
        title="Applications by status"
        description="Where applications received in this period stand right now"
        loading={loading}
        error={error}
        onRetry={() => void query.refetch()}
        height={300}
        srSummary={status.map((s) => `${s.label}: ${s.value}`).join(', ')}
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={status}
            layout="vertical"
            margin={{ top: 4, right: 36, bottom: 4, left: 4 }}
            barCategoryGap={10}
          >
            <CartesianGrid horizontal={false} stroke={chartTheme.grid} />
            <XAxis
              type="number"
              allowDecimals={false}
              tick={chartTheme.axis}
              tickLine={false}
              axisLine={false}
              domain={[0, (max: number) => Math.max(4, max)]}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={92}
              tick={chartTheme.axis}
              tickLine={false}
              axisLine={false}
            />
            <ChartTooltip
              cursor={chartTheme.tooltip.cursor}
              contentStyle={chartTheme.tooltip.contentStyle}
              labelStyle={chartTheme.tooltip.labelStyle}
              formatter={(v) => [fmt.int(v as number), 'Applications']}
            />
            <Bar
              dataKey="value"
              fill="var(--chart-1)"
              barSize={18}
              radius={[0, 4, 4, 0]}
              isAnimationActive={false}
            >
              <LabelList dataKey="value" position="right" fill="var(--foreground)" fontSize={12} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard
        title="Applications over time"
        description={
          totalSeries === 0
            ? 'No applications were received in this period'
            : `${fmt.int(totalSeries)} received, by ${data?.period.granularity ?? 'day'}`
        }
        loading={loading}
        error={error}
        onRetry={() => void query.refetch()}
        height={300}
        srSummary={`${fmt.int(totalSeries)} applications received across ${series.length} periods`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 8, right: 12, bottom: 4, left: -16 }}>
            <defs>
              <linearGradient id="appsOverTime" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.3} />
                <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke={chartTheme.grid} />
            <XAxis dataKey="label" tick={chartTheme.axis} tickLine={false} axisLine={false} minTickGap={24} />
            <YAxis
              allowDecimals={false}
              tick={chartTheme.axis}
              tickLine={false}
              axisLine={false}
              domain={[0, (max: number) => Math.max(3, max)]}
            />
            <ChartTooltip
              contentStyle={chartTheme.tooltip.contentStyle}
              labelStyle={chartTheme.tooltip.labelStyle}
              formatter={(v) => [fmt.int(v as number), 'Applications']}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke="var(--chart-1)"
              strokeWidth={2}
              fill="url(#appsOverTime)"
              isAnimationActive={false}
            />
          </AreaChart>
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
          {status.map((s) => (
            <tr key={s.label}>
              <th scope="row">{s.label}</th>
              <td>{s.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
