import { CalendarClock } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DataTable, type Column } from '@/components/common/DataTable'
import { MatchScoreBadge } from '@/components/common/MatchScore'
import { StatusBadge } from '@/components/common/StatusBadge'
import type { ApplicationListItem, ApplicationStatus } from '@/lib/api'
import { dates } from '@/lib/format'
import { paths } from '@/routes/paths'
import { MoveMenu } from './MoveMenu'

export function ApplicationsTable({
  rows,
  loading,
  error,
  onRetry,
  pendingId,
  onMove,
  sort,
  onSortChange,
  pagination,
  empty,
}: {
  rows: ApplicationListItem[] | undefined
  loading: boolean
  error?: unknown
  onRetry: () => void
  pendingId: string | null
  onMove: (app: ApplicationListItem, target: ApplicationStatus) => void
  sort: string
  onSortChange: (sort: string) => void
  pagination: {
    page?: number
    pages?: number
    total?: number
    pageSize?: number
    onPageChange: (page: number) => void
  }
  empty: React.ReactNode
}) {
  const columns: Column<ApplicationListItem>[] = [
    {
      key: 'candidate',
      header: 'Candidate',
      cell: (a) => (
        <div className="min-w-0 max-w-xs">
          <Link
            to={paths.application(a.id)}
            className="block truncate rounded-sm font-medium hover:text-primary hover:underline"
          >
            {a.candidate_name}
          </Link>
          {a.candidate_headline && (
            <p className="truncate text-xs text-muted-foreground">{a.candidate_headline}</p>
          )}
        </div>
      ),
    },
    {
      key: 'job',
      header: 'Job',
      hideBelow: 'md',
      cell: (a) => (
        <Link
          to={paths.job(a.job_id)}
          className="block max-w-56 truncate rounded-sm hover:text-primary hover:underline"
        >
          {a.job_title}
        </Link>
      ),
    },
    { key: 'status', header: 'Status', cell: (a) => <StatusBadge kind="application" status={a.status} /> },
    {
      key: 'match',
      header: 'Match',
      sortKey: 'match',
      cell: (a) =>
        a.match_score != null ? (
          <MatchScoreBadge score={a.match_score} band={a.match_band} />
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: 'applied',
      header: 'Applied',
      sortKey: 'applied',
      hideBelow: 'lg',
      cell: (a) => (
        <span className="whitespace-nowrap text-muted-foreground" title={dates.dateTime(a.applied_at)}>
          {dates.relative(a.applied_at)}
        </span>
      ),
    },
    {
      key: 'interview',
      header: 'Next interview',
      hideBelow: 'xl',
      cell: (a) =>
        a.next_interview_at ? (
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <CalendarClock className="size-3.5 text-muted-foreground" aria-hidden />
            {dates.dateTime(a.next_interview_at)}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (a) => (
        <MoveMenu
          name={a.candidate_name}
          status={a.status}
          disabled={pendingId === a.id}
          onMove={(t) => onMove(a, t)}
        />
      ),
    },
  ]

  // Two backend orders per column: Applied toggles newest/oldest, Match is "best first" only.
  const sortKey = sort === 'match' ? 'match' : sort === 'newest' || sort === 'oldest' ? 'applied' : undefined
  const direction: 'asc' | 'desc' | undefined =
    sort === 'match' ? 'desc' : sort === 'oldest' ? 'asc' : sort === 'newest' ? 'desc' : undefined

  return (
    <DataTable
      caption="Applications"
      columns={columns}
      rows={rows}
      rowKey={(a) => a.id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      sortKey={sortKey}
      sortDirection={direction}
      onSortChange={(key) =>
        onSortChange(key === 'match' ? 'match' : sort === 'newest' ? 'oldest' : 'newest')
      }
      page={pagination.page}
      pages={pagination.pages}
      total={pagination.total}
      pageSize={pagination.pageSize}
      onPageChange={pagination.onPageChange}
      empty={empty}
      renderCard={(a) => (
        <div className="flex items-start gap-3 p-4">
          <div className="min-w-0 flex-1 space-y-1.5">
            <Link
              to={paths.application(a.id)}
              className="block font-medium hover:text-primary hover:underline"
            >
              {a.candidate_name}
            </Link>
            <p className="text-xs text-muted-foreground">{a.job_title}</p>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge kind="application" status={a.status} />
              <MatchScoreBadge score={a.match_score} band={a.match_band} />
              <span className="text-xs text-muted-foreground">{dates.relative(a.applied_at)}</span>
            </div>
          </div>
          <MoveMenu
            name={a.candidate_name}
            status={a.status}
            disabled={pendingId === a.id}
            onMove={(t) => onMove(a, t)}
          />
        </div>
      )}
    />
  )
}
