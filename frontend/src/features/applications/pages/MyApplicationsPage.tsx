import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function MyApplicationsPage() {
  return (
    <UnderConstruction
      title="My applications"
      description="Track every application and its status."
      endpoints={['GET /applications', 'POST /applications/{id}/withdraw']}
    />
  )
}
