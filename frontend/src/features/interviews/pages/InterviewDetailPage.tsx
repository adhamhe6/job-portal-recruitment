import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function InterviewDetailPage() {
  return (
    <UnderConstruction
      title="Interview"
      description="Interview details, participants and feedback."
      endpoints={['GET /interviews/{id}']}
    />
  )
}
