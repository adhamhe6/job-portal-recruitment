import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function InterviewsPage() {
  return (
    <UnderConstruction
      title="Interviews"
      description="Schedule and manage interviews with candidates."
      endpoints={['GET /interviews', 'POST /interviews']}
    />
  )
}
