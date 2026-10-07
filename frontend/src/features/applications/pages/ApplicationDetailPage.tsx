import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function ApplicationDetailPage() {
  return (
    <UnderConstruction
      title="Application"
      description="Application details, history and notes."
      endpoints={['GET /applications/{id}', 'GET /applications/{id}/notes']}
    />
  )
}
