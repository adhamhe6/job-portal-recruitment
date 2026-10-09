import { CalendarClock, CheckCircle2, UserX, Users, XCircle } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { ErrorState } from '@/components/common/States'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { ApiError } from '@/lib/api'
import { paths } from '@/routes/paths'
import { useInterview } from '../api/staff'
import type { StaffInterviewView } from '../api/types'
import { FeedbackSection } from '../components/FeedbackSection'
import { CandidateInterviewCard, HistoryCard, StaffDetailsCard } from '../components/InterviewDetails'
import { useInterviewActions } from '../hooks/useInterviewActions'
import { interviewTypeLabel } from '../lib/labels'
import { feedbackBlockedReason, interviewActions } from '../lib/stateMachine'

function DetailSkeleton() {
  return (
    <div className="space-y-5" role="status" aria-busy="true" aria-label="Loading interview">
      <Skeleton className="h-9 w-2/3" />
      <Skeleton className="h-4 w-1/3" />
      <div className="grid gap-5 lg:grid-cols-3">
        <Skeleton className="h-72 lg:col-span-2" />
        <Skeleton className="h-72" />
      </div>
    </div>
  )
}

function StaffInterview({ iv }: { iv: StaffInterviewView }) {
  const { can, user, hasRole } = useAuth()
  const { request, dialog } = useInterviewActions()
  const actions = interviewActions({
    status: iv.status,
    startAt: iv.start_at,
    canManage: can('schedule_interviews'),
    isParticipant: iv.participants.some((p) => p.user_id === user?.id),
  })
  const mayWrite = hasRole('RECRUITER', 'HIRING_MANAGER') && can('provide_feedback')
  const blocked = iv.can_submit_feedback ? null : feedbackBlockedReason(iv.status, iv.start_at)
  const title = `${interviewTypeLabel(iv.interview_type)} · ${iv.candidate_name}`

  return (
    <>
      <PageHeader
        title={title}
        description={`${iv.job_title} at ${iv.company_name}`}
        breadcrumbs={[{ label: 'Interviews', to: paths.interviews }, { label: iv.candidate_name }]}
        meta={<StatusBadge kind="interview" status={iv.status} />}
        actions={
          actions.any && (
            <>
              {actions.reschedule.allowed && (
                <Button variant="outline" onClick={() => request(iv, 'reschedule')}>
                  <CalendarClock /> Reschedule
                </Button>
              )}
              {(actions.complete.allowed || actions.complete.reason) && (
                <>
                  <Button
                    variant="outline"
                    disabled={!actions.complete.allowed}
                    onClick={() => request(iv, 'complete')}
                  >
                    <CheckCircle2 /> Mark completed
                  </Button>
                  <Button
                    variant="outline"
                    disabled={!actions.noShow.allowed}
                    onClick={() => request(iv, 'no-show')}
                  >
                    <UserX /> No-show
                  </Button>
                </>
              )}
              {actions.cancel.allowed && (
                <Button variant="outline" onClick={() => request(iv, 'cancel')}>
                  <XCircle /> Cancel
                </Button>
              )}
            </>
          )
        }
      />
      {actions.complete.reason && !actions.complete.allowed && (
        <p className="-mt-3 mb-4 text-xs text-muted-foreground">
          Mark completed and no-show:{' '}
          {actions.complete.reason.charAt(0).toLowerCase() + actions.complete.reason.slice(1)}
        </p>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <StaffDetailsCard iv={iv} />
          <FeedbackSection
            interviewId={iv.id}
            canSubmit={iv.can_submit_feedback}
            blockedReason={blocked}
            mayWrite={mayWrite}
          />
        </div>
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Users className="size-5 text-muted-foreground" aria-hidden /> Participants
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="divide-y" aria-label="Participants">
                {iv.participants.map((p) => (
                  <li key={p.user_id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{p.name}</span>
                      <span className="text-xs text-muted-foreground">
                        {p.role === 'INTERVIEWER' ? 'Interviewer' : 'Observer'}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {p.has_submitted_feedback ? 'Feedback submitted' : 'No feedback yet'}
                    </span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Application</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">Current stage</span>
                <StatusBadge kind="application" status={iv.application.status} />
              </div>
              {iv.application.allowed_next_statuses.length > 0 && (
                <p className="text-muted-foreground">
                  Next stage options:{' '}
                  <span className="font-medium text-foreground">
                    {iv.application.allowed_next_statuses.map((s) => APPLICATION_STATUS_LABELS[s]).join(', ')}
                  </span>
                </p>
              )}
              <Button asChild variant="outline" size="sm" className="w-full">
                <Link to={paths.application(iv.application.id)}>Open application</Link>
              </Button>
            </CardContent>
          </Card>

          <HistoryCard iv={iv} />
        </div>
      </div>
      {dialog}
    </>
  )
}

export default function InterviewDetailPage() {
  const { id } = useParams()
  const query = useInterview(id)
  const iv = query.data
  useDocumentTitle(iv ? `Interview · ${iv.job_title}` : 'Interview')

  if (query.isPending) return <DetailSkeleton />
  if (query.isError || !iv) {
    const notFound = query.error instanceof ApiError && query.error.status === 404
    return (
      <>
        <PageHeader
          title="Interview"
          breadcrumbs={[{ label: 'Interviews', to: paths.interviews }, { label: 'Interview' }]}
        />
        <Card>
          <ErrorState
            error={query.error}
            title={notFound ? 'Interview not found' : undefined}
            onRetry={notFound ? undefined : () => query.refetch()}
          />
          {notFound && (
            <div className="flex justify-center pb-8">
              <Button asChild variant="outline">
                <Link to={paths.interviews}>Back to interviews</Link>
              </Button>
            </div>
          )}
        </Card>
      </>
    )
  }

  if (iv.audience === 'candidate') {
    return (
      <>
        <PageHeader
          title={`${interviewTypeLabel(iv.interview_type)} with ${iv.company_name}`}
          description={iv.job_title}
          breadcrumbs={[{ label: 'My interviews', to: paths.interviews }, { label: iv.job_title }]}
          meta={<StatusBadge kind="interview" status={iv.status} />}
        />
        <CandidateInterviewCard iv={iv} />
      </>
    )
  }
  return <StaffInterview iv={iv} />
}
