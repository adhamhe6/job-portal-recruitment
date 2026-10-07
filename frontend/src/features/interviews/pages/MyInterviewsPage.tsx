import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function MyInterviewsPage() {
  return (
    <UnderConstruction
      title="My interviews"
      description="Your upcoming and past interviews."
      endpoints={['GET /interviews']}
    />
  )
}
