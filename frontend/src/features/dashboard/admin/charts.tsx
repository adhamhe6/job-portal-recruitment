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
import { fmt } from '@/lib/format'

export interface BarDatum {
  label: string
  value: number
}

function SrTable({
  caption,
  head,
  rows,
}: {
  caption: string
  head: [string, string]
  rows: [string, number][]
}) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th scope="col">{head[0]}</th>
          <th scope="col">{head[1]}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <th scope="row">{k}</th>
            <td>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Horizontal bar chart of a category -> count distribution, with a text alternative and a hidden data table. */
export function DistributionChart({
  title,
  description,
  unit,
  data,
  loading,
  error,
  onRetry,
}: {
  title: string
  description: string
  unit: string
  data: BarDatum[] | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const rows = data ?? []
  const total = rows.reduce((n, r) => n + r.value, 0)
  const summary = rows.map((r) => `${r.label}: ${r.value}`).join(', ')
  return (
    <section>
      <ChartCard
        title={title}
        description={total === 0 && !loading ? `${description} (no data yet)` : description}
        loading={loading}
        error={error}
        onRetry={onRetry}
        height={Math.max(200, rows.length * 34 + 24)}
        srSummary={summary}
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 4, right: 36, bottom: 4, left: 4 }}
            barCategoryGap={10}
          >
            <CartesianGrid horizontal={false} stroke={chartTheme.grid} strokeWidth={1} />
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
              width={104}
              tick={chartTheme.axis}
              tickLine={false}
              axisLine={false}
            />
            <ChartTooltip
              cursor={chartTheme.tooltip.cursor}
              contentStyle={chartTheme.tooltip.contentStyle}
              labelStyle={chartTheme.tooltip.labelStyle}
              formatter={(v) => [fmt.int(v as number), unit]}
            />
            <Bar
              dataKey="value"
              name={unit}
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
      {!loading && !error && (
        <SrTable caption={title} head={['Category', unit]} rows={rows.map((r) => [r.label, r.value])} />
      )}
    </section>
  )
}

const shortDay = (iso: string) => {
  try {
    return format(parseISO(iso), 'MMM d')
  } catch {
    return iso
  }
}

/** Single-series area chart over time (daily or weekly buckets). */
export function TimeSeriesChart({
  title,
  description,
  unit,
  points,
  loading,
  error,
  onRetry,
}: {
  title: string
  description: string
  unit: string
  points: { bucket: string; count: number }[] | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const rows = points ?? []
  const total = rows.reduce((n, p) => n + p.count, 0)
  const peak = rows.reduce(
    (best, p) => (p.count > best.count ? p : best),
    rows[0] ?? { bucket: '', count: 0 },
  )
  const summary =
    rows.length === 0
      ? 'No data'
      : `${fmt.int(total)} ${unit.toLowerCase()} between ${shortDay(rows[0]!.bucket)} and ${shortDay(rows[rows.length - 1]!.bucket)}; busiest period starts ${shortDay(peak.bucket)} with ${peak.count}.`
  return (
    <section>
      <ChartCard
        title={title}
        description={description}
        loading={loading}
        error={error}
        onRetry={onRetry}
        height={240}
        srSummary={summary}
      >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid vertical={false} stroke={chartTheme.grid} strokeWidth={1} />
            <XAxis
              dataKey="bucket"
              tickFormatter={shortDay}
              tick={chartTheme.axis}
              tickLine={false}
              axisLine={false}
              minTickGap={24}
            />
            <YAxis
              allowDecimals={false}
              tick={chartTheme.axis}
              tickLine={false}
              axisLine={false}
              domain={[0, (m: number) => Math.max(4, m)]}
            />
            <ChartTooltip
              cursor={chartTheme.tooltip.cursor}
              contentStyle={chartTheme.tooltip.contentStyle}
              labelStyle={chartTheme.tooltip.labelStyle}
              labelFormatter={(l) => shortDay(String(l))}
              formatter={(v) => [fmt.int(v as number), unit]}
            />
            <Area
              type="monotone"
              dataKey="count"
              name={unit}
              stroke="var(--chart-1)"
              strokeWidth={2}
              fill="var(--chart-1)"
              fillOpacity={0.15}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </ChartCard>
      {!loading && !error && (
        <SrTable
          caption={title}
          head={['Period starting', unit]}
          rows={rows.map((p) => [p.bucket, p.count])}
        />
      )}
    </section>
  )
}
