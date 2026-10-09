import { Building2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState } from '@/components/common/States'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { paths } from '@/routes/paths'
import { useMyCompany } from '../api/company'
import { CompanyProfileForm } from '../components/CompanyProfileForm'

export default function CompanySettingsPage() {
  useDocumentTitle('Company settings')
  const { user } = useAuth()
  const hasCompany = Boolean(user?.company_id)
  const query = useMyCompany(hasCompany)
  // Company administrators (recruiters) and platform administrators may edit; everyone else sees the profile read-only.
  const canEdit = Boolean(
    user && (user.role === 'ADMIN' || (user.role === 'RECRUITER' && user.is_company_admin)),
  )

  if (!hasCompany)
    return (
      <EmptyState
        icon={<Building2 aria-hidden />}
        title="Your account is not attached to a company"
        description={
          user?.role === 'ADMIN'
            ? 'Platform administrators manage tenant companies from the admin area.'
            : 'Ask a platform administrator to attach your account to a company.'
        }
        action={
          user?.role === 'ADMIN' ? (
            <Button asChild>
              <Link to={paths.adminCompanies}>Manage companies</Link>
            </Button>
          ) : undefined
        }
      />
    )

  if (query.isPending)
    return (
      <div className="space-y-4" role="status" aria-busy="true" aria-label="Loading company profile">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    )
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  return (
    <div className="grid gap-4">
      {query.data.status === 'SUSPENDED' && (
        <Badge variant="danger" className="w-fit">
          This company is suspended by a platform administrator
        </Badge>
      )}
      {/* Remount when the saved profile changes underneath (another admin edited it), so the form shows fresh values. */}
      <CompanyProfileForm key={query.data.updated_at} company={query.data} canEdit={canEdit} />
    </div>
  )
}
