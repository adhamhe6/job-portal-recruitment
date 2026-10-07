import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function AdminDashboardPage() {
  return (
    <UnderConstruction
      title="Dashboard"
      description="Platform-wide activity, companies and system health."
      endpoints={['GET /reports/admin/…', 'GET /admin/…']}
    />
  )
}
