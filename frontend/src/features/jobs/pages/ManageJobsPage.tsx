import { Briefcase, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DataTable, type Column } from '@/components/common/DataTable'
import { PageHeader } from '@/components/common/PageHeader'
import { SearchInput } from '@/components/common/SearchInput'
import { EmptyState, NoResults } from '@/components/common/States'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import type { JobListItem } from '@/lib/api'
import { JOB_STATUS_LABELS } from '@/lib/enums'
import { dates, deadlineHint, fmt } from '@/lib/format'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { useManagedJobs } from '../api/jobs'
import { JobRowActions } from '../components/JobRowActions'
import { useJobLifecycle } from '../hooks/useJobLifecycle'

const PAGE_SIZE = 10
const STATUS_TABS = ['ALL', 'DRAFT', 'PUBLISHED', 'PAUSED', 'CLOSED', 'ARCHIVED'] as const
const SORTS = [
  { value: 'newest', label: 'Recently updated' },
  { value: 'title', label: 'Title A–Z' },
  { value: 'deadline', label: 'Deadline: soonest' },
  { value: 'salary_desc', label: 'Salary: high to low' },
  { value: 'salary_asc', label: 'Salary: low to high' },
]

function DeadlineCell({ deadline }: { deadline: string | null }) {
  if (!deadline) return <span className="text-muted-foreground">—</span>
  const hint = deadlineHint(deadline)
  return (
    <span className={cn('whitespace-nowrap', hint?.tone === 'past' && 'text-destructive', hint?.tone === 'urgent' && 'font-medium text-amber-700 dark:text-amber-400')}>
      {dates.date(deadline)}
    </span>
  )
}

export default function ManageJobsPage() {
  useDocumentTitle('Jobs')
  const { can, user, isAdmin } = useAuth()
  const [state, update, reset] = useUrlState({ q: '', status: 'ALL', sort: 'newest', page: 1 })
  const status = (STATUS_TABS as readonly string[]).includes(state.status) ? state.status : 'ALL'
  const query = useManagedJobs({ q: state.q, status, sort: state.sort, page: state.page, pageSize: PAGE_SIZE })
  const { request, dialog } = useJobLifecycle()
  const canCreate = can('manage_jobs') && !isAdmin
  const hasFilters = Boolean(state.q.trim()) || status !== 'ALL'

  const columns: Column<JobListItem>[] = [
    {
      key: 'title',
      header: 'Job',
      cell: (j) => (
        <div className="min-w-0 max-w-sm">
          <Link to={paths.job(j.id)} className="block truncate rounded-sm font-medium hover:text-primary hover:underline">
            {j.title}
          </Link>
          <p className="truncate text-xs text-muted-foreground">{[j.department, j.location].filter(Boolean).join(' · ') || '—'}</p>
        </div>
      ),
    },
    { key: 'status', header: 'Status', cell: (j) => <StatusBadge kind="job" status={j.status} /> },
    {
      key: 'apps',
      header: 'Applications',
      align: 'right',
      cell: (j) => (
        <Link to={`${paths.applications}?job_id=${j.id}`} className="rounded-sm font-medium tabular hover:text-primary hover:underline" aria-label={`${j.application_count ?? 0} applications for ${j.title}`}>
          {fmt.int(j.application_count ?? 0)}
        </Link>
      ),
    },
    {
      key: 'posted',
      header: 'Published',
      hideBelow: 'lg',
      cell: (j) => (j.published_at ? <span className="whitespace-nowrap text-muted-foreground">{dates.relative(j.published_at)}</span> : <span className="text-muted-foreground">Not published</span>),
    },
    { key: 'deadline', header: 'Deadline', hideBelow: 'md', cell: (j) => <DeadlineCell deadline={j.application_deadline} /> },
    { key: 'actions', header: <span className="sr-only">Actions</span>, align: 'right', cell: (j) => <JobRowActions job={j} onAction={request} /> },
  ]

  const emptyNoJobs = (
    <EmptyState
      icon={<Briefcase aria-hidden />}
      title={user?.role === 'HIRING_MANAGER' ? 'No jobs assigned to you yet' : 'No jobs yet'}
      description={user?.role === 'HIRING_MANAGER' ? 'Jobs a recruiter assigns to you will appear here.' : 'Create your first job posting to start receiving matched applications.'}
      action={
        canCreate && (
          <Button asChild>
            <Link to={paths.manageJobNew}>
              <Plus /> Create a job
            </Link>
          </Button>
        )
      }
    />
  )

  return (
    <>
      <PageHeader
        title="Jobs"
        description={user?.role === 'HIRING_MANAGER' ? 'Jobs assigned to you.' : isAdmin ? 'All jobs across companies.' : `Manage ${user?.company?.name ?? 'your company'}'s job postings.`}
        actions={
          canCreate && (
            <Button asChild>
              <Link to={paths.manageJobNew}>
                <Plus /> New job
              </Link>
            </Button>
          )
        }
      />

      <Tabs value={status} onValueChange={(v) => update({ status: v })}>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <TabsList aria-label="Filter by status">
            {STATUS_TABS.map((s) => (
              <TabsTrigger key={s} value={s}>
                {s === 'ALL' ? 'All' : JOB_STATUS_LABELS[s]}
              </TabsTrigger>
            ))}
          </TabsList>
          <SearchInput className="min-w-52 flex-1 basis-60 sm:max-w-sm" value={state.q} onChange={(q) => update({ q })} placeholder="Search jobs by title or skill" label="Search jobs" />
          <div className="ml-auto flex items-center gap-2">
            <label htmlFor="manage-sort" className="sr-only">
              Sort by
            </label>
            <NativeSelect id="manage-sort" className="w-48" value={state.sort} onChange={(e) => update({ sort: e.target.value })}>
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </NativeSelect>
          </div>
        </div>

        <TabsContent value={status} forceMount className="mt-0">
          <Card className="overflow-hidden">
            <DataTable
              caption="Jobs"
              columns={columns}
              rows={query.data?.items}
              rowKey={(j) => j.id}
              loading={query.isFetching}
              error={query.isError && !query.data ? query.error : undefined}
              onRetry={() => query.refetch()}
              page={query.data?.page}
              pages={query.data?.pages}
              total={query.data?.total}
              pageSize={query.data?.page_size}
              onPageChange={(p) => update({ page: p }, { resetPage: false })}
              empty={
                hasFilters ? (
                  <NoResults
                    title="No jobs match"
                    description="Try a different status or search term."
                    action={
                      <Button variant="outline" onClick={() => reset(['q', 'status', 'page'])}>
                        Clear filters
                      </Button>
                    }
                  />
                ) : (
                  emptyNoJobs
                )
              }
              renderCard={(j) => (
                <div className="flex items-start gap-3 p-4">
                  <div className="min-w-0 flex-1 space-y-2">
                    <Link to={paths.job(j.id)} className="block font-medium hover:text-primary hover:underline">
                      {j.title}
                    </Link>
                    <p className="text-xs text-muted-foreground">{[j.department, j.location].filter(Boolean).join(' · ')}</p>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      <StatusBadge kind="job" status={j.status} />
                      <Link to={`${paths.applications}?job_id=${j.id}`} className="font-medium text-foreground hover:underline">
                        {fmt.int(j.application_count ?? 0)} applications
                      </Link>
                      {j.application_deadline && <span>Deadline {dates.date(j.application_deadline)}</span>}
                    </div>
                  </div>
                  <JobRowActions job={j} onAction={request} />
                </div>
              )}
            />
          </Card>
        </TabsContent>
      </Tabs>
      {dialog}
    </>
  )
}
