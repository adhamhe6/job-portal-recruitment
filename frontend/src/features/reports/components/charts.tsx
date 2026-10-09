import type { ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { chartTheme } from '@/components/common/ChartCard'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

export interface BarDatum {
  label: string
  value: number
  /** Text shown at the end of the bar (defaults to the formatted value). */
  text?: string
}

/**
 * Horizontal bar chart in the shared chart style (single series, 18 px bars, rounded data end, hairline grid, labels
 * in text colours). The chart is decorative for assistive tech: pair it with `<DataTable>`/`<SrTable>` or the
 * `srSummary` of its `ChartCard`.
 */
export function HBarChart({
  data,
  name,
  format = (v) => String(v),
  color = 'var(--chart-1)',
  labelWidth = 104,
  rightMargin = 56,
}: {
  data: BarDatum[]
  /** Series name for the tooltip ("Applications"). */
  name: string
  format?: (v: number) => string
  color?: string
  labelWidth?: number
  rightMargin?: number
}) {
  const rows = data.map((d) => ({ ...d, text: d.text ?? format(d.value) }))
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={rows}
        layout="vertical"
        margin={{ top: 4, right: rightMargin, bottom: 4, left: 4 }}
        barCategoryGap={10}
      >
        <CartesianGrid horizontal={false} stroke={chartTheme.grid} strokeWidth={1} />
        <XAxis
          type="number"
          allowDecimals
          tick={chartTheme.axis}
          tickLine={false}
          axisLine={false}
          domain={[0, (max: number) => Math.max(1, max)]}
        />
        <YAxis
          type="category"
          dataKey="label"
          width={labelWidth}
          tick={chartTheme.axis}
          tickLine={false}
          axisLine={false}
          interval={0}
        />
        <ChartTooltip
          cursor={chartTheme.tooltip.cursor}
          contentStyle={chartTheme.tooltip.contentStyle}
          labelStyle={chartTheme.tooltip.labelStyle}
          formatter={(v) => [format(v as number), name]}
        />
        <Bar
          dataKey="value"
          name={name}
          fill={color}
          barSize={18}
          radius={[0, 4, 4, 0]}
          isAnimationActive={false}
        >
          <LabelList dataKey="text" position="right" fill="var(--foreground)" fontSize={12} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export interface TableColumn<T> {
  key: string
  header: string
  align?: 'left' | 'right'
  cell: (row: T) => ReactNode
}

/** Small read-only data table (visible, scrolls inside its card on phones). */
export function SimpleTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  className,
  srOnly,
}: {
  caption: string
  columns: TableColumn<T>[]
  rows: T[]
  rowKey: (row: T) => string
  className?: string
  srOnly?: boolean
}) {
  const table = (
    <Table className={srOnly ? 'sr-only' : undefined}>
      <caption className="sr-only">{caption}</caption>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {columns.map((c) => (
            <TableHead key={c.key} scope="col" className={cn(c.align === 'right' && 'text-right')}>
              {c.header}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={rowKey(row)}>
            {columns.map((c) => (
              <TableCell key={c.key} className={cn('tabular', c.align === 'right' && 'text-right')}>
                {c.cell(row)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
  if (srOnly) return table
  return <Card className={cn('overflow-hidden', className)}>{table}</Card>
}
