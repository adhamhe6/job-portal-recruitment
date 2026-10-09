import { useMemo } from 'react'
import { FilterBar, type ActiveFilter } from '@/components/common/FilterBar'
import { PageHeader } from '@/components/common/PageHeader'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input, NativeSelect } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useManagedJobs } from '@/features/jobs/api/jobs'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { InterviewsTab } from '../components/InterviewsTab'
import { ExportMenu, ExportStatus } from '../components/ExportMenu'
import { isJobSort, JobsTab } from '../components/JobsTab'
import { OverviewTab } from '../components/OverviewTab'
import { PipelineTab } from '../components/PipelineTab'
import { SourcesTab } from '../components/SourcesTab'
import { useCsvExport } from '../hooks/useCsvExport'
import { exportById } from '../lib/exports'
import { activePreset, DATE_PRESETS } from '../lib/presets'
import type { JobPerformanceSort, ReportFilters } from '../api/types'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'pipeline', label: 'Pipeline & timing' },
  { id: 'jobs', label: 'Job performance' },
  { id: 'sources', label: 'Sources & skills' },
  { id: 'interviews', label: 'Interviews & matching' },
] as const
type TabId = (typeof TABS)[number]['id']
const isTab = (v: string): v is TabId => TABS.some((t) => t.id === v)

export default function ReportsPage() {
  useDocumentTitle('Reports')
  const [state, update, reset] = useUrlState({
    tab: 'overview',
    from: '',
    to: '',
    job: '',
    sort: 'applications',
    order: 'desc',
    page: 1,
  })
  const tab: TabId = isTab(state.tab) ? state.tab : 'overview'
  const sort: JobPerformanceSort = isJobSort(state.sort) ? state.sort : 'applications'
  const order = state.order === 'asc' ? 'asc' : 'desc'
  const rangeInvalid = Boolean(state.from && state.to && state.from > state.to)
  const jobs = useManagedJobs({ q: '', status: 'ALL', sort: 'title', page: 1, pageSize: 100 })

  const filters = useMemo<ReportFilters>(
    () => ({ from: rangeInvalid ? '' : state.from, to: rangeInvalid ? '' : state.to, jobId: state.job }),
    [state.from, state.to, state.job, rangeInvalid],
  )
  const jobSort = useMemo(() => ({ sort, order }), [sort, order])
  const exporter = useCsvExport(filters, jobSort)

  const preset = activePreset(state.from, state.to)
  const jobTitle = jobs.data?.items.find((j) => j.id === state.job)?.title
  const active: ActiveFilter[] = [
    ...(state.from || state.to
      ? [
          {
            key: 'range',
            label: `Period: ${state.from || 'start'} to ${state.to || 'today'}`,
            onRemove: () => update({ from: '', to: '' }),
          },
        ]
      : []),
    ...(state.job
      ? [{ key: 'job', label: `Job: ${jobTitle ?? 'Selected job'}`, onRemove: () => update({ job: '' }) }]
      : []),
  ]

  const exportJobs = () => {
    const def = exportById('job-performance')
    if (def) void exporter.start(def)
  }

  return (
    <>
      <PageHeader
        title="Reports"
        description="Hiring funnel, speed, sources and interviews for the period you choose."
        actions={
          <ExportMenu filters={filters} busy={exporter.busy} onExport={(d) => void exporter.start(d)} />
        }
      />
      <ExportStatus
        state={exporter.state}
        onRetry={(d) => void exporter.start(d)}
        onDismiss={exporter.dismiss}
      />

      <FilterBar
        className="mb-5"
        active={active}
        onClearAll={() => reset(['from', 'to', 'job', 'page'])}
        trailing={
          <div role="group" aria-label="Date range presets" className="flex flex-wrap gap-1">
            {DATE_PRESETS.map((p) => (
              <Button
                key={p.id}
                size="sm"
                variant={preset === p.id ? 'soft' : 'outline'}
                aria-pressed={preset === p.id}
                onClick={() => update(p.range())}
              >
                {p.label}
              </Button>
            ))}
          </div>
        }
      >
        <div className="flex items-center gap-2">
          <Label htmlFor="rep-from" className="text-xs text-muted-foreground">
            From
          </Label>
          <Input
            id="rep-from"
            type="date"
            className="w-40"
            value={state.from}
            max={state.to || undefined}
            aria-invalid={rangeInvalid || undefined}
            onChange={(e) => update({ from: e.target.value })}
          />
          <Label htmlFor="rep-to" className="text-xs text-muted-foreground">
            To
          </Label>
          <Input
            id="rep-to"
            type="date"
            className="w-40"
            value={state.to}
            min={state.from || undefined}
            aria-invalid={rangeInvalid || undefined}
            onChange={(e) => update({ to: e.target.value })}
          />
        </div>
        <div className="w-56">
          <Label htmlFor="rep-job" className="sr-only">
            Job
          </Label>
          <NativeSelect id="rep-job" value={state.job} onChange={(e) => update({ job: e.target.value })}>
            <option value="">All jobs</option>
            {jobs.data?.items.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title}
              </option>
            ))}
          </NativeSelect>
        </div>
      </FilterBar>

      {rangeInvalid && (
        <Alert variant="warning" className="mb-4" title="Check the date range">
          The start date is after the end date, so the range is ignored until you fix it. Dates are calendar
          days in UTC.
        </Alert>
      )}
      {state.job && tab !== 'overview' && (
        <p className="mb-4 text-xs text-muted-foreground">
          The job filter applies to the funnel, status and pipeline figures only; the other reports cover all
          jobs.
        </p>
      )}

      <Tabs value={tab} onValueChange={(v) => update({ tab: v })}>
        <div className="mb-5 overflow-x-auto">
          <TabsList aria-label="Report sections">
            {TABS.map((t) => (
              <TabsTrigger key={t.id} value={t.id}>
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value="overview" className="mt-0">
          <OverviewTab filters={filters} />
        </TabsContent>
        <TabsContent value="pipeline" className="mt-0">
          <PipelineTab filters={filters} />
        </TabsContent>
        <TabsContent value="jobs" className="mt-0">
          <JobsTab
            filters={filters}
            page={state.page}
            sort={sort}
            order={order}
            onPageChange={(p) => update({ page: p }, { resetPage: false })}
            onSortChange={(k) =>
              update({
                sort: k,
                order: k === sort ? (order === 'desc' ? 'asc' : 'desc') : k === 'title' ? 'asc' : 'desc',
              })
            }
            onExport={exportJobs}
            exporting={exporter.state.status === 'running' && exporter.state.def.id === 'job-performance'}
          />
        </TabsContent>
        <TabsContent value="sources" className="mt-0">
          <SourcesTab filters={filters} />
        </TabsContent>
        <TabsContent value="interviews" className="mt-0">
          <InterviewsTab filters={filters} />
        </TabsContent>
      </Tabs>
    </>
  )
}
