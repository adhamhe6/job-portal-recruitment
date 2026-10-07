import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function TeamSettingsPage() {
  return (
    <UnderConstruction
      title="Team"
      description="Recruiters and hiring managers in your company."
      endpoints={['GET /companies/{id}/members', 'POST /companies/{id}/members']}
    />
  )
}
