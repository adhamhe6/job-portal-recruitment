import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function UsersPage() {
  return (
    <UnderConstruction
      title="Users"
      description="Manage user accounts and roles."
      endpoints={['GET /users', 'PATCH /users/{id}']}
    />
  )
}
