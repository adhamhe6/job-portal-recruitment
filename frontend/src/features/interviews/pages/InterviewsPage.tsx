import { CalendarDays, CalendarX2, List } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { DataTable, type Column } from '@/components/common/DataTable'
import { FilterBar, type ActiveFilter } from '@/components/common/FilterBar'
import { PageHeader } from '@/components/common/PageHeader'
import { EmptyState, ErrorState, NoResults, TableSkeleton } from '@/components/common/States'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { MultiSelect } from '@/components/ui/combobox'
import { Input, NativeSelect } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Pagination } from '@/components/ui/pagination'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useCompanyMembers } from '@/features/companies/api/companies'
import { useManagedJobs } from '@/features/jobs/api/jobs'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { useInterviews, type InterviewFilters } from '../api/staff'
import {
  INTERVIEW_STATUSES,
  isStaffInterview,
  type InterviewStatus,
  type StaffInterviewItem,
} from '../api/types'
import { InterviewAgenda, StaffInterviewCard } from '../components/InterviewAgenda'
import { InterviewRowActions } from '../components/InterviewRowActions'
import { InterviewTime, ParticipantNames } from '../components/InterviewParts'
import { NewInterviewButton } from '../components/NewInterviewButton'
import { useInterviewActions } from '../hooks/useInterviewActions'
import { groupByDay } from '../lib/agenda'
import { INTERVIEW_STATUS_LABELS, INTERVIEW_STATUS_OPTIONS, interviewTypeLabel } from '../lib/labels'
import { formatDay, viewerTimeZone } from '../lib/time'

const AGENDA_PAGE_SIZE = 50
const TABLE_PAGE_SIZE = 20
/** The API has no interviewer filter, so that one filter is applied to a full (100) page on the client. */
const CLIENT_FILTER_PAGE_SIZE = 100

const isStatus = (s: string): s is InterviewStatus => (INTERVIEW_STATUSES as readonly string[]).includes(s)

export default function InterviewsPage() {
  useDocumentTitle('Interviews')
  const { can, user } = useAuth()
  const viewerTz = useMemo(() => viewerTimeZone(), [])
  const [state, update, reset] = useUrlState({
    view: 'agenda',
    status: [] as string[],
    job: '',
    who: '',
    from: '',
    to: '',
    upcoming: '1',
    sort: 'start_asc',
    page: 1,
  })
  const view = state.view === 'table' ? 'table' : 'agenda'
  const statuses = state.status.filter(isStatus)
  const upcomingOnly = state.upcoming !== '0'
  const sort = state.sort === 'start_desc' ? 'start_desc' : 'start_asc'
  const rangeInvalid = Boolean(state.from && state.to && state.from > state.to)
  const pageSize = state.who ? CLIENT_FILTER_PAGE_SIZE : view === 'table' ? TABLE_PAGE_SIZE : AGENDA_PAGE_SIZE
  const filters: InterviewFilters = {
    status: statuses,
    jobId: state.job,
    from: state.from,
    to: state.to,
    upcomingOnly,
    sort,
    page: state.who ? 1 : state.page,
    pageSize,
  }
  const query = useInterviews(filters, !rangeInvalid)
  const jobs = useManagedJobs({ q: '', status: 'ALL', sort: 'title', page: 1, pageSize: 100 })
  const members = useCompanyMembers(user?.company_id)
  const canSchedule = can('schedule_interviews')
  const { request, dialog } = useInterviewActions()

  const loaded = useMemo(() => (query.data?.items ?? []).filter(isStaffInterview), [query.data?.items])
  const items = useMemo(
    () => (state.who ? loaded.filter((i) => i.participants.some((p) => p.user_id === state.who)) : loaded),
    [loaded, state.who],
  )
  const days = useMemo(() => groupByDay(items, viewerTz), [items, viewerTz])

  // Interviewer choices: the company team; admins (no company) get whoever appears in the loaded results.
  const interviewerOptions = useMemo(() => {
    const map = new Map<string, string>()
    for (const m of members.data ?? []) {
      if (m.status === 'ACTIVE') map.set(m.id, `${m.first_name} ${m.last_name}`.trim())
    }
    for (const iv of loaded)
      for (const p of iv.participants) if (!map.has(p.user_id)) map.set(p.user_id, p.name)
    return [...map.entries()]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [members.data, loaded])

  const jobTitle = jobs.data?.items.find((j) => j.id === state.job)?.title
  const active: ActiveFilter[] = [
    ...statuses.map((s) => ({
      key: `status-${s}`,
      label: `Status: ${INTERVIEW_STATUS_LABELS[s]}`,
      onRemove: () => update({ status: statuses.filter((x) => x !== s) }),
    })),
    ...(state.job
      ? [{ key: 'job', label: `Job: ${jobTitle ?? 'Selected job'}`, onRemove: () => update({ job: '' }) }]
      : []),
    ...(state.who
      ? [
          {
            key: 'who',
            label: `Interviewer: ${interviewerOptions.find((o) => o.value === state.who)?.label ?? 'Selected'}`,
            onRemove: () => update({ who: '' }),
          },
        ]
      : []),
    ...(state.from
      ? [{ key: 'from', label: `From ${state.from}`, onRemove: () => update({ from: '' }) }]
      : []),
    ...(state.to ? [{ key: 'to', label: `To ${state.to}`, onRemove: () => update({ to: '' }) }] : []),
    ...(!upcomingOnly
      ? [{ key: 'past', label: 'Including past interviews', onRemove: () => update({ upcoming: '1' }) }]
      : []),
  ]
  const hasFilters = active.length > 0
  const clearAll = () => reset(['status', 'job', 'who', 'from', 'to', 'upcoming', 'page'])
  const total = query.data?.total ?? 0
  const truncated = Boolean(state.who) && total > CLIENT_FILTER_PAGE_SIZE

  const columns: Column<StaffInterviewItem>[] = [
    {
      key: 'when',
      header: 'When',
      cell: (iv) => (
        <div className="text-sm">
          <p className="whitespace-nowrap text-muted-foreground">{formatDay(iv.start_at, viewerTz)}</p>
          <InterviewTime startAt={iv.start_at} endAt={iv.end_at} timezone={iv.timezone} viewerTz={viewerTz} />
        </div>
      ),
    },
    {
      key: 'candidate',
      header: 'Candidate',
      cell: (iv) => (
        <div className="min-w-0 max-w-64">
          <Link
            to={paths.interview(iv.id)}
            className="block truncate rounded-sm font-medium hover:text-primary hover:underline"
          >
            {iv.candidate_name}
          </Link>
          <p className="truncate text-xs text-muted-foreground">{iv.job_title}</p>
        </div>
      ),
    },
    { key: 'type', header: 'Type', hideBelow: 'lg', cell: (iv) => interviewTypeLabel(iv.interview_type) },
    { key: 'status', header: 'Status', cell: (iv) => <StatusBadge kind="interview" status={iv.status} /> },
    {
      key: 'who',
      header: 'Interviewers',
      hideBelow: 'xl',
      cell: (iv) => <ParticipantNames participants={iv.participants} />,
    },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (iv) => <InterviewRowActions interview={iv} onAction={request} />,
    },
  ]

  const empty = hasFilters ? (
    <NoResults
      title="No interviews match"
      description={
        upcomingOnly
          ? 'Try different filters, or include past interviews.'
          : 'Try a different status, job or date range.'
      }
      action={
        <Button variant="outline" onClick={clearAll}>
          Clear filters
        </Button>
      }
    />
  ) : (
    <EmptyState
      icon={<CalendarX2 aria-hidden />}
      title="No upcoming interviews"
      description={
        canSchedule
          ? 'Schedule an interview for a shortlisted candidate, or include past interviews to see history.'
          : 'Interviews you take part in will appear here.'
      }
      action={
        <>
          {canSchedule && <NewInterviewButton />}
          <Button variant="outline" onClick={() => update({ upcoming: '0' })}>
            Show past interviews
          </Button>
        </>
      }
    />
  )

  return (
    <>
      <PageHeader
        title="Interviews"
        description={
          user?.role === 'HIRING_MANAGER'
            ? 'Interviews for your jobs and the ones you take part in.'
            : 'Every interview across your hiring pipeline, by day.'
        }
        actions={canSchedule && <NewInterviewButton />}
      />

      <FilterBar
        className="mb-5"
        active={active}
        onClearAll={clearAll}
        trailing={
          <>
            <div className="flex items-center gap-2">
              <Label htmlFor="iv-sort" className="sr-only">
                Sort by
              </Label>
              <NativeSelect
                id="iv-sort"
                className="w-40"
                value={sort}
                onChange={(e) => update({ sort: e.target.value })}
              >
                <option value="start_asc">Soonest first</option>
                <option value="start_desc">Latest first</option>
              </NativeSelect>
            </div>
            <div role="group" aria-label="View" className="inline-flex rounded-lg border bg-card p-0.5">
              {(
                [
                  ['agenda', 'Agenda', CalendarDays],
                  ['table', 'List', List],
                ] as const
              ).map(([value, label, Icon]) => (
                <Button
                  key={value}
                  size="sm"
                  variant={view === value ? 'soft' : 'ghost'}
                  aria-pressed={view === value}
                  onClick={() => update({ view: value }, { resetPage: true })}
                >
                  <Icon /> {label}
                </Button>
              ))}
            </div>
          </>
        }
      >
        <div className="w-44">
          <MultiSelect
            aria-label="Status"
            values={statuses}
            onChange={(v) => update({ status: v })}
            options={INTERVIEW_STATUS_OPTIONS}
            placeholder="Any status"
            searchPlaceholder="Search statuses…"
            showChips={false}
          />
        </div>
        <div className="w-48">
          <Label htmlFor="iv-job" className="sr-only">
            Job
          </Label>
          <NativeSelect id="iv-job" value={state.job} onChange={(e) => update({ job: e.target.value })}>
            <option value="">All jobs</option>
            {jobs.data?.items.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="w-48">
          <Label htmlFor="iv-who" className="sr-only">
            Interviewer
          </Label>
          <NativeSelect id="iv-who" value={state.who} onChange={(e) => update({ who: e.target.value })}>
            <option value="">All interviewers</option>
            {interviewerOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor="iv-from" className="text-xs text-muted-foreground">
            From
          </Label>
          <Input
            id="iv-from"
            type="date"
            className="w-40"
            value={state.from}
            max={state.to || undefined}
            aria-invalid={rangeInvalid || undefined}
            onChange={(e) => update({ from: e.target.value })}
          />
          <Label htmlFor="iv-to" className="text-xs text-muted-foreground">
            To
          </Label>
          <Input
            id="iv-to"
            type="date"
            className="w-40"
            value={state.to}
            min={state.from || undefined}
            aria-invalid={rangeInvalid || undefined}
            onChange={(e) => update({ to: e.target.value })}
          />
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Checkbox
            id="iv-upcoming"
            checked={upcomingOnly}
            onCheckedChange={(c) => update({ upcoming: c === true ? '1' : '0' })}
          />
          <Label htmlFor="iv-upcoming" className="cursor-pointer">
            Upcoming only
          </Label>
        </div>
      </FilterBar>

      {rangeInvalid && (
        <Alert variant="warning" className="mb-4" title="Check the date range">
          The start date is after the end date. Dates are calendar days in UTC.
        </Alert>
      )}
      {truncated && (
        <Alert variant="info" className="mb-4">
          Showing the first {CLIENT_FILTER_PAGE_SIZE} of {total} matching interviews for this interviewer
          filter. Narrow the date range or status to see the rest.
        </Alert>
      )}

      {rangeInvalid ? null : query.isError && !query.data ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      ) : view === 'table' ? (
        <Card className="overflow-hidden">
          <DataTable
            caption="Interviews"
            columns={columns}
            rows={query.data ? items : undefined}
            rowKey={(iv) => iv.id}
            loading={query.isFetching}
            page={state.who ? undefined : query.data?.page}
            pages={state.who ? undefined : query.data?.pages}
            total={state.who ? undefined : query.data?.total}
            pageSize={state.who ? undefined : query.data?.page_size}
            onPageChange={(p) => update({ page: p }, { resetPage: false })}
            empty={empty}
            renderCard={(iv) => <StaffInterviewCard interview={iv} viewerTz={viewerTz} onAction={request} />}
          />
        </Card>
      ) : !query.data ? (
        <Card>
          <TableSkeleton rows={5} cols={4} />
        </Card>
      ) : items.length === 0 ? (
        <Card>{empty}</Card>
      ) : (
        <>
          <InterviewAgenda days={days} viewerTz={viewerTz} onAction={request} busy={query.isFetching} />
          {!state.who && (
            <Pagination
              className={cn('mt-2')}
              page={query.data.page}
              pages={query.data.pages}
              total={query.data.total}
              pageSize={query.data.page_size}
              onPageChange={(p) => update({ page: p }, { resetPage: false })}
              label="interviews"
            />
          )}
        </>
      )}
      <p className="mt-4 text-xs text-muted-foreground">
        Times are shown in your timezone ({viewerTz.replace(/_/g, ' ')}). When an interview was set up in
        another timezone, that time is shown as well.
      </p>
      {dialog}
    </>
  )
}
