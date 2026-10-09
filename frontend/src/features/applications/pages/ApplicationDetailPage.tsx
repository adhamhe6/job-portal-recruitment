import { useParams } from 'react-router-dom'
import { ErrorState } from '@/components/common/States'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { ApiError } from '@/lib/api'
import { useApplication } from '../api/applications'
import { CandidateApplicationView } from '../components/CandidateApplicationView'
import { StaffApplicationView } from '../components/StaffApplicationView'

function DetailSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading application">
      <div className="space-y-2">
        <Skeleton className="h-8 w-72 max-w-full" />
        <Skeleton className="h-4 w-48" />
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-6">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-56 w-full" />
        </div>
        <Skeleton className="h-72 w-full" />
      </div>
    </div>
  )
}

export default function ApplicationDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { isCandidate } = useAuth()
  const query = useApplication(id)
  useDocumentTitle(
    query.data
      ? `${isCandidate ? query.data.job_title : query.data.candidate_name} · Application`
      : 'Application',
  )

  if (query.isPending) return <DetailSkeleton />
  if (query.isError) {
    const notFound =
      query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 403)
    return (
      <ErrorState
        error={query.error}
        onRetry={() => query.refetch()}
        title={notFound ? 'Application not found' : undefined}
      />
    )
  }
  return isCandidate ? (
    <CandidateApplicationView application={query.data} />
  ) : (
    <StaffApplicationView application={query.data} />
  )
}
