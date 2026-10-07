import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function ProfilePage() {
  return (
    <UnderConstruction
      title="Profile"
      description="Your experience, education, skills and job preferences."
      endpoints={['GET /candidates/me', 'PATCH /candidates/me']}
    />
  )
}
