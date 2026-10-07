import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function CandidateDashboardPage() {
  return (
    <UnderConstruction
      title="Dashboard"
      description="Your applications, upcoming interviews and best-matching jobs at a glance."
      endpoints={['GET /applications', 'GET /recommendations/jobs', 'GET /candidates/me/completion']}
    />
  )
}
