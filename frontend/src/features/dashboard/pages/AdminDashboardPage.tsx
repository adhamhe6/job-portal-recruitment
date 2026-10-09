import { Briefcase, Building2, ClipboardList, RefreshCw, Target, Users } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { KpiCard } from '@/components/common/KpiCard'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { adminKeys, useAdminDashboard } from '@/features/admin/api/admin'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { APPLICATION_STATUS_LABELS, JOB_STATUS_LABELS, ROLE_LABELS } from '@/lib/enums'
import { dates, fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import { usePlatformApplications } from '../admin/api'
import { DistributionChart, TimeSeriesChart, type BarDatum } from '../admin/charts'
import { HealthSummary } from '../admin/HealthSummary'
import { RecentActivity } from '../admin/RecentActivity'

/** Fixed category order with zero-filled gaps; unknown keys the API may add later are appended. */
function distribution(
  by: Record<string, number> | undefined,
  labels: Record<string, string>,
): BarDatum[] | undefined {
  if (!by) return undefined
  const known = Object.keys(labels).map((k) => ({ label: labels[k] ?? k, value: by[k] ?? 0 }))
  const extra = Object.keys(by)
    .filter((k) => !(k in labels))
    .map((k) => ({ label: fmt.label(k), value: by[k] ?? 0 }))
  return [...known, ...extra]
}

const sum = (by: Record<string, number> | undefined) =>
  by ? Object.values(by).reduce((a, b) => a + b, 0) : 0

export default function AdminDashboardPage() {
  useDocumentTitle('Dashboard')
  const qc = useQueryClient()
  const dash = useAdminDashboard()
  const apps = usePlatformApplications()
  const d = dash.data
  const loading = dash.isPending
  const err = dash.isError ? dash.error : undefined

  return (
    <>
      <PageHeader
        title="Platform overview"
        description="Accounts, companies, hiring activity and system health across the whole platform."
        meta={
          d && (
            <span className="text-xs text-muted-foreground" role="status">
              Generated {dates.relative(d.generated_at)}
            </span>
          )
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            loading={dash.isFetching && !dash.isPending}
            onClick={() => void qc.invalidateQueries({ queryKey: adminKeys.all })}
          >
            <RefreshCw /> Refresh
          </Button>
        }
      />

      <div className="space-y-6">
        <section aria-label="Key figures" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <KpiCard
            label="Users"
            value={fmt.int(d?.users_total)}
            icon={<Users />}
            loading={loading}
            to={paths.adminUsers}
            hint={d ? `${fmt.int(d.users_by_status.SUSPENDED ?? 0)} suspended` : undefined}
          />
          <KpiCard
            label="Companies"
            value={fmt.int(d?.companies.total)}
            icon={<Building2 />}
            tone="info"
            loading={loading}
            to={paths.adminCompanies}
            hint={
              d
                ? `${fmt.int(d.companies.active)} active · ${fmt.int(d.companies.suspended)} suspended`
                : undefined
            }
          />
          <KpiCard
            label="Published jobs"
            value={fmt.int(d?.jobs_by_status.PUBLISHED ?? 0)}
            icon={<Briefcase />}
            tone="success"
            loading={loading}
            hint={d ? `${fmt.int(sum(d.jobs_by_status))} jobs in total` : undefined}
          />
          <KpiCard
            label="Applications"
            value={fmt.int(sum(d?.applications_by_status))}
            icon={<ClipboardList />}
            tone="warning"
            loading={loading}
            hint={d ? `${fmt.int(d.applications_by_status.HIRED ?? 0)} hired` : undefined}
          />
          <KpiCard
            label="Match pairs"
            value={fmt.int(d?.matches.pairs)}
            icon={<Target />}
            tone="info"
            loading={loading}
            hint={
              d
                ? d.matches.last_generated_at
                  ? `Last computed ${dates.relative(d.matches.last_generated_at)}`
                  : 'None computed yet'
                : undefined
            }
          />
        </section>

        <section aria-label="Activity over time" className="grid gap-4 lg:grid-cols-2">
          <TimeSeriesChart
            title="Applications received"
            description={
              apps.data
                ? `New applications per ${apps.data.period.granularity}, ${dates.date(apps.data.period.from_date)} to ${dates.date(apps.data.period.to_date)}`
                : 'New applications over the last 30 days'
            }
            unit="Applications"
            points={apps.data?.applications_over_time}
            loading={apps.isPending}
            error={apps.isError ? apps.error : undefined}
            onRetry={() => apps.refetch()}
          />
          <TimeSeriesChart
            title="New sign-ups"
            description="Accounts created per day over the last 30 days"
            unit="Sign-ups"
            points={d?.signups_over_time}
            loading={loading}
            error={err}
            onRetry={() => dash.refetch()}
          />
        </section>

        <section aria-label="Distributions" className="grid gap-4 lg:grid-cols-3">
          <DistributionChart
            title="Users by role"
            description="All accounts on the platform"
            unit="Users"
            data={distribution(d?.users_by_role, ROLE_LABELS)}
            loading={loading}
            error={err}
            onRetry={() => dash.refetch()}
          />
          <DistributionChart
            title="Jobs by status"
            description="Every job, by lifecycle stage"
            unit="Jobs"
            data={distribution(d?.jobs_by_status, JOB_STATUS_LABELS)}
            loading={loading}
            error={err}
            onRetry={() => dash.refetch()}
          />
          <DistributionChart
            title="Applications by status"
            description="Current status of every application"
            unit="Applications"
            data={distribution(d?.applications_by_status, APPLICATION_STATUS_LABELS)}
            loading={loading}
            error={err}
            onRetry={() => dash.refetch()}
          />
        </section>

        <section aria-label="Operations" className="grid gap-4 lg:grid-cols-2">
          <HealthSummary />
          <RecentActivity
            events={d?.recent_audit_events}
            loading={loading}
            error={err}
            onRetry={() => dash.refetch()}
          />
        </section>
      </div>
    </>
  )
}
