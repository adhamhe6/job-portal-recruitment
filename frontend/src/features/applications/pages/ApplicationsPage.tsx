import { Columns3, Inbox, Table2 } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { FilterBar, type ActiveFilter } from '@/components/common/FilterBar'
import { PageHeader } from '@/components/common/PageHeader'
import { SearchInput } from '@/components/common/SearchInput'
import { EmptyState, ErrorState, NoResults } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { SimpleSelect } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useManagedJobs } from '@/features/jobs/api/jobs'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { pluralize } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { useApplications } from '../api/applications'
import { ApplicationsTable } from '../components/ApplicationsTable'
import { PipelineBoard } from '../components/PipelineBoard'
import { useStatusChange } from '../hooks/useStatusChange'
import { ALL_STAGES } from '../lib/workflow'

const SORTS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'updated', label: 'Recently updated' },
  { value: 'match', label: 'Best match score' },
]
const STATUS_OPTIONS = ALL_STAGES.map((s) => ({ value: s, label: APPLICATION_STATUS_LABELS[s] }))
const TABLE_PAGE_SIZE = 20
const BOARD_PAGE_SIZE = 100

export default function ApplicationsPage() {
  useDocumentTitle('Applications')
  const { user, can } = useAuth()
  const [state, update, reset] = useUrlState({
    view: 'board',
    job_id: '',
    status: '',
    q: '',
    sort: 'newest',
    page: 1,
  })
  const view = state.view === 'table' ? 'table' : 'board'
  const status = (ALL_STAGES as string[]).includes(state.status) ? state.status : ''
  const sort = SORTS.some((s) => s.value === state.sort) ? state.sort : 'newest'
  const pageSize = view === 'board' ? BOARD_PAGE_SIZE : TABLE_PAGE_SIZE

  const query = useApplications({ jobId: state.job_id, status, q: state.q, sort, page: state.page, pageSize })
  const jobs = useManagedJobs({ q: '', status: 'ALL', sort: 'title', page: 1, pageSize: 100 })
  const { request, dialog, pendingId } = useStatusChange()

  const jobOptions = useMemo(() => {
    const opts = (jobs.data?.items ?? []).map((j) => ({ value: j.id, label: j.title }))
    if (state.job_id && !opts.some((o) => o.value === state.job_id)) {
      const fromApp = query.data?.items.find((a) => a.job_id === state.job_id)
      opts.unshift({ value: state.job_id, label: fromApp?.job_title ?? 'Selected job' })
    }
    return opts
  }, [jobs.data, state.job_id, query.data])
  const jobLabel = jobOptions.find((o) => o.value === state.job_id)?.label

  const active: ActiveFilter[] = [
    ...(state.job_id
      ? [{ key: 'job', label: `Job: ${jobLabel ?? 'Selected job'}`, onRemove: () => update({ job_id: '' }) }]
      : []),
    ...(status
      ? [
          {
            key: 'status',
            label: `Status: ${APPLICATION_STATUS_LABELS[status as keyof typeof APPLICATION_STATUS_LABELS]}`,
            onRemove: () => update({ status: '' }),
          },
        ]
      : []),
    ...(state.q.trim()
      ? [{ key: 'q', label: `Search: ${state.q.trim()}`, onRemove: () => update({ q: '' }) }]
      : []),
  ]
  const clearAll = () => reset(['job_id', 'status', 'q', 'page'])

  const data = query.data
  const noApplications = (
    <EmptyState
      icon={<Inbox aria-hidden />}
      title="No applications yet"
      description={
        user?.role === 'HIRING_MANAGER'
          ? 'Applications for jobs assigned to you will appear here.'
          : 'Applications appear here as soon as candidates apply to your published jobs.'
      }
      action={
        <Button asChild variant="outline">
          <Link to={paths.manageJobs}>View your jobs</Link>
        </Button>
      }
    />
  )
  const noMatches = (
    <NoResults
      title="No applications match"
      description="Try a different job, status or search term."
      action={
        <Button variant="outline" onClick={clearAll}>
          Clear filters
        </Button>
      }
    />
  )
  const emptyNode = active.length > 0 ? noMatches : noApplications

  return (
    <>
      <PageHeader
        title="Applications"
        description={
          user?.role === 'HIRING_MANAGER'
            ? 'Review applicants for the jobs assigned to you.'
            : 'Review and move applicants through your hiring pipeline.'
        }
        meta={data ? pluralize(data.total, 'application') : undefined}
      />

      <Tabs value={view} onValueChange={(v) => update({ view: v })}>
        <FilterBar
          className="mb-4"
          active={active}
          onClearAll={clearAll}
          trailing={
            <>
              <div>
                <label htmlFor="apps-sort" className="sr-only">
                  Sort by
                </label>
                <NativeSelect
                  id="apps-sort"
                  className="w-44"
                  value={sort}
                  onChange={(e) => update({ sort: e.target.value })}
                >
                  {SORTS.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <TabsList aria-label="View">
                <TabsTrigger value="board">
                  <Columns3 className="size-4" aria-hidden /> Board
                </TabsTrigger>
                <TabsTrigger value="table">
                  <Table2 className="size-4" aria-hidden /> Table
                </TabsTrigger>
              </TabsList>
            </>
          }
        >
          <SearchInput
            className="min-w-52 flex-1 basis-60 sm:max-w-xs"
            value={state.q}
            onChange={(q) => update({ q })}
            placeholder="Search candidate or job"
            label="Search applications"
          />
          <SimpleSelect
            aria-label="Filter by job"
            className="w-full sm:w-56"
            value={state.job_id}
            onValueChange={(v) => update({ job_id: v })}
            options={jobOptions}
            emptyLabel="All jobs"
            placeholder="All jobs"
          />
          <SimpleSelect
            aria-label="Filter by status"
            className="w-full sm:w-44"
            value={status}
            onValueChange={(v) => update({ status: v })}
            options={STATUS_OPTIONS}
            emptyLabel="All statuses"
            placeholder="All statuses"
          />
        </FilterBar>

        <div aria-live="polite" className="sr-only">
          {data ? `${pluralize(data.total, 'application')} found` : ''}
        </div>

        <TabsContent value={view} className="mt-0">
          {view === 'board' ? (
            query.isError && !data ? (
              <Card>
                <ErrorState error={query.error} onRetry={() => query.refetch()} />
              </Card>
            ) : data && data.items.length === 0 ? (
              <Card>{emptyNode}</Card>
            ) : (
              <div className={query.isFetching && data ? 'opacity-70 transition-opacity' : undefined}>
                <PipelineBoard
                  items={data?.items}
                  loading={query.isPending}
                  pendingId={pendingId}
                  onMove={request}
                />
                {data && data.pages > 1 && (
                  <Pagination
                    className="mt-3"
                    page={data.page}
                    pages={data.pages}
                    total={data.total}
                    pageSize={data.page_size}
                    onPageChange={(p) => update({ page: p }, { resetPage: false })}
                    label="applications"
                  />
                )}
                {data && can('manage_applications') && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Drag a card to the next stage, or use its “Move” menu to change a stage with the keyboard.
                  </p>
                )}
              </div>
            )
          ) : (
            <Card className="overflow-hidden">
              <ApplicationsTable
                rows={data?.items}
                loading={query.isFetching}
                error={query.isError && !data ? query.error : undefined}
                onRetry={() => query.refetch()}
                pendingId={pendingId}
                onMove={request}
                sort={sort}
                onSortChange={(s) => update({ sort: s })}
                pagination={{
                  page: data?.page,
                  pages: data?.pages,
                  total: data?.total,
                  pageSize: data?.page_size,
                  onPageChange: (p) => update({ page: p }, { resetPage: false }),
                }}
                empty={emptyNode}
              />
            </Card>
          )}
        </TabsContent>
      </Tabs>
      {dialog}
    </>
  )
}
