import { Briefcase, CalendarClock, Gift, UserRound } from 'lucide-react'
import { Link } from 'react-router-dom'
import { KpiCard } from '@/components/common/KpiCard'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { paths } from '@/routes/paths'
import {
  ApplicationsByStatus,
  ProfileProgress,
  RecentNotifications,
  TopRecommendations,
  UpcomingInterviews,
  useDashboardKpis,
} from '../candidate/sections'

export default function CandidateDashboardPage() {
  useDocumentTitle('Dashboard')
  const { user } = useAuth()
  const { apps, interviews, completion, active, offers } = useDashboardKpis()

  return (
    <>
      <PageHeader
        title={user ? `Welcome back, ${user.first_name}` : 'Dashboard'}
        description="Your applications, upcoming interviews and best-matching jobs at a glance."
        actions={
          <Button asChild>
            <Link to={paths.jobs}>Find jobs</Link>
          </Button>
        }
      />

      <section aria-label="Key figures" className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Active applications"
          value={active ?? '—'}
          hint={apps.data ? `${apps.data.total} in total` : undefined}
          icon={<Briefcase />}
          to={paths.applications}
          loading={apps.isPending}
        />
        <KpiCard
          label="Upcoming interviews"
          value={interviews.data?.total ?? '—'}
          hint="Scheduled, not yet held"
          icon={<CalendarClock />}
          tone="warning"
          to={paths.interviews}
          loading={interviews.isPending}
        />
        <KpiCard
          label="Offers"
          value={offers ?? '—'}
          hint="Applications at offer stage"
          icon={<Gift />}
          tone="success"
          to={`${paths.applications}?status=OFFER`}
          loading={apps.isPending}
        />
        <KpiCard
          label="Profile completeness"
          value={completion.data ? `${completion.data.percent}%` : '—'}
          hint={completion.data?.missing[0]}
          icon={<UserRound />}
          tone="info"
          to={paths.profile}
          loading={completion.isPending}
        />
      </section>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <ApplicationsByStatus />
        <UpcomingInterviews />
        <TopRecommendations />
        <div className="grid gap-6">
          <ProfileProgress />
          <RecentNotifications />
        </div>
      </div>
    </>
  )
}
