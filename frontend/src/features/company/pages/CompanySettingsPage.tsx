import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function CompanySettingsPage() {
  return (
    <UnderConstruction
      title="Company settings"
      description="Your company profile as candidates see it."
      endpoints={['GET /companies/me', 'PATCH /companies/{id}']}
    />
  )
}
