import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function MatchingPage() {
  return (
    <UnderConstruction
      title="Candidate matching"
      description="Ranked candidates for each of your jobs, with explanations."
      endpoints={['GET /matches/jobs/{id}/candidates', 'POST /matches/jobs/{id}/refresh']}
    />
  )
}
