import { Briefcase, CalendarDays, User } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { StatusBadge } from '@/components/common/StatusBadge'
import { TextBlock } from '@/components/common/TextBlock'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { ApplicationDetail } from '@/lib/api'
import { dates, fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import { ApplicationInterviews } from './ApplicationInterviews'
import { HistoryTimeline } from './HistoryTimeline'
import { MatchPanel } from './MatchPanel'
import { NotesPanel } from './NotesPanel'
import { ResumeButton } from './ResumeButton'
import { StageActions } from './StageActions'
import { StageProgress } from './StageProgress'

/** Hiring-team view: candidate summary, match explanation, workflow actions, audit history, notes and interviews. */
export function StaffApplicationView({ application: a }: { application: ApplicationDetail }) {
  const { can } = useAuth()
  const canViewCandidate = can('view_candidates')
  const canManage = can('manage_applications')

  return (
    <>
      <PageHeader
        title={a.candidate_name}
        description={`Applied for ${a.job_title}`}
        breadcrumbs={[{ label: 'Applications', to: paths.applications }, { label: a.candidate_name }]}
        meta={<StatusBadge kind="application" status={a.status} />}
        actions={
          <>
            {canViewCandidate && (
              <Button asChild variant="outline">
                <Link to={paths.candidate(a.candidate_id)}>
                  <User /> Candidate profile
                </Link>
              </Button>
            )}
            <Button asChild variant="outline">
              <Link to={paths.job(a.job_id)}>
                <Briefcase /> View job
              </Link>
            </Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Stage</CardTitle>
              <CardDescription>Changed {dates.relative(a.status_changed_at)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <StageProgress status={a.status} audience="staff" />
              {a.status === 'REJECTED' && a.rejection_reason && (
                <p className="text-sm">
                  <span className="font-medium">Reason: </span>
                  <span className="text-muted-foreground">{a.rejection_reason}</span>
                </p>
              )}
              {canManage ? (
                <StageActions application={a} />
              ) : (
                <Alert variant="info">
                  You have read-only access: only recruiters can move applications between stages.
                </Alert>
              )}
            </CardContent>
          </Card>

          <MatchPanel application={a} />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Cover letter</CardTitle>
            </CardHeader>
            <CardContent>
              {a.cover_letter ? (
                <TextBlock text={a.cover_letter} />
              ) : (
                <p className="text-sm text-muted-foreground">The candidate did not include a cover letter.</p>
              )}
            </CardContent>
          </Card>

          <NotesPanel applicationId={a.id} />
        </div>

        <aside aria-label="Application summary" className="space-y-6">
          <Card>
            <CardContent className="space-y-3 p-5 text-sm">
              <p className="flex items-center gap-2">
                <CalendarDays className="size-4 text-muted-foreground" aria-hidden /> Applied{' '}
                {dates.date(a.applied_at)}
              </p>
              <p className="text-muted-foreground">Source: {fmt.label(a.source)}</p>
              <ResumeButton resumeId={a.resume_id} filename={a.resume_filename} />
            </CardContent>
          </Card>
          <ApplicationInterviews applicationId={a.id} status={a.status} />
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Status history</CardTitle>
              <CardDescription>Every stage change is recorded with who made it.</CardDescription>
            </CardHeader>
            <CardContent>
              <HistoryTimeline history={a.history} />
            </CardContent>
          </Card>
        </aside>
      </div>
    </>
  )
}
