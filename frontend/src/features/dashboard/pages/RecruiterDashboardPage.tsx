import { Briefcase, CalendarCheck, ClipboardList, Star, UserCheck } from 'lucide-react'
import { lazy, Suspense } from 'react'
import { KpiCard } from '@/components/common/KpiCard'
import { PageHeader } from '@/components/common/PageHeader'
import { ErrorState } from '@/components/common/States'
import { NativeSelect } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { dates, fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import { RANGE_OPTIONS, useRecruiterDashboard, useUpcomingInterviews } from '../api/dashboard'
import {
  FunnelPanel,
  RecentActivityPanel,
  TopJobsPanel,
  UpcomingInterviewsPanel,
} from '../components/DashboardPanels'

// Recharts is heavy: load it only when the dashboard is opened.
const DashboardCharts = lazy(() => import('../components/DashboardCharts'))

const chartsFallback = (
  <div className="grid gap-4 lg:grid-cols-2" role="status" aria-label="Loading charts">
    <Skeleton className="h-[26rem] w-full" />
    <Skeleton className="h-[26rem] w-full" />
  </div>
)

export default function RecruiterDashboardPage() {
  useDocumentTitle('Dashboard')
  const { user } = useAuth()
  const [{ range }, update] = useUrlState({ range: '30' })
  const days = RANGE_OPTIONS.some((o) => o.value === range) ? Number(range) : 30
  const query = useRecruiterDashboard(days)
  const interviews = useUpcomingInterviews(5)
  const k = query.data?.kpis
  const loading = query.isPending
  const rangeLabel = RANGE_OPTIONS.find((o) => o.value === String(days))?.label.toLowerCase() ?? 'this period'
  const manager = user?.role === 'HIRING_MANAGER'

  return (
    <>
      <PageHeader
        title={`Welcome back${user?.first_name ? `, ${user.first_name}` : ''}`}
        description={
          manager
            ? 'Hiring activity for the jobs assigned to you.'
            : `Hiring activity across ${user?.company?.name ?? 'your company'}.`
        }
        meta={query.data ? `Updated ${dates.relative(query.data.generated_at)}` : undefined}
        actions={
          <div className="flex items-center gap-2">
            <label htmlFor="dash-range" className="sr-only">
              Reporting period
            </label>
            <NativeSelect
              id="dash-range"
              className="w-40"
              value={String(days)}
              onChange={(e) => update({ range: e.target.value })}
            >
              {RANGE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </NativeSelect>
          </div>
        }
      />

      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className="space-y-6">
          <section aria-label="Key figures" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <KpiCard
              label="Open jobs"
              value={fmt.int(k?.active_jobs)}
              icon={<Briefcase />}
              hint={
                k && k.jobs_nearing_deadline > 0
                  ? `${k.jobs_nearing_deadline} closing within 7 days`
                  : 'Published right now'
              }
              to={paths.manageJobs}
              loading={loading}
            />
            <KpiCard
              label="Applications"
              value={fmt.int(k?.total_applications)}
              icon={<ClipboardList />}
              tone="info"
              hint={k ? `${rangeLabel} · ${k.applications_in_screening} in screening` : undefined}
              to={paths.applications}
              loading={loading}
            />
            <KpiCard
              label="Shortlisted"
              value={fmt.int(k?.shortlisted)}
              icon={<Star />}
              tone="warning"
              hint="Currently shortlisted"
              to={`${paths.applications}?status=SHORTLISTED`}
              loading={loading}
            />
            <KpiCard
              label="Interviews this week"
              value={fmt.int(k?.upcoming_interviews)}
              icon={<CalendarCheck />}
              tone="info"
              hint="Starting in the next 7 days"
              to={paths.interviews}
              loading={loading}
            />
            <KpiCard
              label="Hires"
              value={fmt.int(k?.hires_in_period)}
              icon={<UserCheck />}
              tone="success"
              hint={rangeLabel}
              to={`${paths.applications}?status=HIRED`}
              loading={loading}
            />
          </section>

          <Suspense fallback={chartsFallback}>
            <DashboardCharts data={query.data} query={query} />
          </Suspense>

          <div className="grid gap-4 lg:grid-cols-2">
            <FunnelPanel query={query} />
            <TopJobsPanel query={query} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <UpcomingInterviewsPanel query={interviews} />
            <RecentActivityPanel query={query} />
          </div>
        </div>
      )}
    </>
  )
}
