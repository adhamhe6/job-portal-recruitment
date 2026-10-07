import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function CompaniesPage() {
  return (
    <UnderConstruction
      title="Companies"
      description="Manage tenant companies."
      endpoints={['GET /companies', 'PATCH /companies/{id}']}
    />
  )
}
