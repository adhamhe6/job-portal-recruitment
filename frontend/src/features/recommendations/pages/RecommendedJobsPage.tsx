import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function RecommendedJobsPage() {
  return (
    <UnderConstruction
      title="Recommended jobs"
      description="Jobs ranked by how well they fit your profile, with the reasons why."
      endpoints={['GET /recommendations/jobs', 'POST /recommendations/refresh']}
    />
  )
}
