import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function ApplicationsPage() {
  return (
    <UnderConstruction
      title="Applications"
      description="Review and move applicants through your hiring pipeline."
      endpoints={['GET /applications', 'POST /applications/{id}/status']}
    />
  )
}
