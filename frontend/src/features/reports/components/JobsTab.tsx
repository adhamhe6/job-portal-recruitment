import { Download } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DataTable, type Column } from '@/components/common/DataTable'
import { EmptyState } from '@/components/common/States'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { fmt } from '@/lib/format'
import { pluralize } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { useJobPerformance } from '../api/reports'
import type { JobPerformanceRow, JobPerformanceSort, ReportFilters } from '../api/types'

export const JOB_PAGE_SIZE = 10
const SORT_KEYS: JobPerformanceSort[] = [
  'applications',
  'title',
  'shortlist_rate',
  'hire_rate',
  'avg_days_to_hire',
  'avg_match_score',
]
export const isJobSort = (v: string): v is JobPerformanceSort => (SORT_KEYS as string[]).includes(v)

const days = (v: number | null) => (v === null ? '—' : `${fmt.num(v)} d`)

export function JobsTab({
  filters,
  page,
  sort,
  order,
  onPageChange,
  onSortChange,
  onExport,
  exporting,
}: {
  filters: ReportFilters
  page: number
  sort: JobPerformanceSort
  order: 'asc' | 'desc'
  onPageChange: (page: number) => void
  onSortChange: (sort: JobPerformanceSort) => void
  onExport: () => void
  exporting: boolean
}) {
  const query = useJobPerformance(filters, { page, pageSize: JOB_PAGE_SIZE, sort, order })

  const columns: Column<JobPerformanceRow>[] = [
    {
      key: 'title',
      header: 'Job',
      sortKey: 'title',
      cell: (r) => (
        <div className="min-w-0 max-w-64">
          <Link
            to={paths.job(r.job_id)}
            className="block truncate rounded-sm font-medium hover:text-primary hover:underline"
          >
            {r.title}
          </Link>
          <StatusBadge kind="job" status={r.job_status} className="mt-1" />
        </div>
      ),
    },
    {
      key: 'applications',
      header: 'Applications',
      sortKey: 'applications',
      align: 'right',
      cell: (r) => (
        <Link
          to={`${paths.applications}?job_id=${r.job_id}`}
          className="rounded-sm font-medium tabular hover:text-primary hover:underline"
          aria-label={`${pluralize(r.applications, 'application')} for ${r.title}`}
        >
          {fmt.int(r.applications)}
        </Link>
      ),
    },
    {
      key: 'shortlist',
      header: 'Shortlist rate',
      sortKey: 'shortlist_rate',
      align: 'right',
      hideBelow: 'md',
      cell: (r) => <span className="tabular">{fmt.percent(r.shortlist_rate, 0)}</span>,
    },
    {
      key: 'hire',
      header: 'Hires',
      sortKey: 'hire_rate',
      align: 'right',
      cell: (r) => (
        <span className="tabular">
          {fmt.int(r.hires)} <span className="text-muted-foreground">({fmt.percent(r.hire_rate, 0)})</span>
        </span>
      ),
    },
    {
      key: 'first',
      header: 'First response',
      align: 'right',
      hideBelow: 'xl',
      cell: (r) => <span className="tabular">{days(r.avg_days_to_first_status_change)}</span>,
    },
    {
      key: 'tth',
      header: 'Days to hire',
      sortKey: 'avg_days_to_hire',
      align: 'right',
      hideBelow: 'lg',
      cell: (r) => <span className="tabular">{days(r.avg_days_to_hire)}</span>,
    },
    {
      key: 'match',
      header: 'Avg. match',
      sortKey: 'avg_match_score',
      align: 'right',
      hideBelow: 'lg',
      cell: (r) => <span className="tabular">{fmt.percent(r.avg_match_score, 0)}</span>,
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {query.data?.note ?? 'Applications, conversion and speed per job in the selected period.'}
        </p>
        <Button variant="outline" size="sm" onClick={onExport} loading={exporting}>
          <Download /> Export CSV
        </Button>
      </div>
      <Card className="overflow-hidden">
        <DataTable
          caption="Job performance"
          columns={columns}
          rows={query.data?.items}
          rowKey={(r) => r.job_id}
          loading={query.isFetching}
          error={query.isError && !query.data ? query.error : undefined}
          onRetry={() => query.refetch()}
          sortKey={sort}
          sortDirection={order}
          onSortChange={(k) => isJobSort(k) && onSortChange(k)}
          page={query.data?.page}
          pages={query.data?.pages}
          total={query.data?.total}
          pageSize={query.data?.page_size}
          onPageChange={onPageChange}
          empty={
            <EmptyState
              title="No jobs received applications"
              description="Jobs appear here once candidates apply in the selected period."
            />
          }
          renderCard={(r) => (
            <div className="space-y-2 p-4">
              <div className="flex items-start justify-between gap-3">
                <Link to={paths.job(r.job_id)} className="font-medium hover:text-primary hover:underline">
                  {r.title}
                </Link>
                <StatusBadge kind="job" status={r.job_status} />
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <dt>Applications</dt>
                <dd className="text-right font-medium text-foreground tabular">{fmt.int(r.applications)}</dd>
                <dt>Shortlist rate</dt>
                <dd className="text-right font-medium text-foreground tabular">
                  {fmt.percent(r.shortlist_rate, 0)}
                </dd>
                <dt>Hires</dt>
                <dd className="text-right font-medium text-foreground tabular">
                  {fmt.int(r.hires)} ({fmt.percent(r.hire_rate, 0)})
                </dd>
                <dt>Days to hire</dt>
                <dd className="text-right font-medium text-foreground tabular">{days(r.avg_days_to_hire)}</dd>
                <dt>Avg. match</dt>
                <dd className="text-right font-medium text-foreground tabular">
                  {fmt.percent(r.avg_match_score, 0)}
                </dd>
              </dl>
            </div>
          )}
        />
      </Card>
    </div>
  )
}
