import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function RecruiterDashboardPage() {
  return (
    <UnderConstruction
      title="Dashboard"
      description="Hiring pipeline, open roles and the candidates that need your attention."
      endpoints={['GET /jobs', 'GET /applications', 'GET /reports/…']}
    />
  )
}
