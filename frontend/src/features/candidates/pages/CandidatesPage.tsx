import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function CandidatesPage() {
  return (
    <UnderConstruction
      title="Candidates"
      description="Search and shortlist candidates."
      endpoints={['GET /search/candidates']}
    />
  )
}
