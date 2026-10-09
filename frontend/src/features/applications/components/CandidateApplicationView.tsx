import { Building2, CalendarDays, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageHeader } from '@/components/common/PageHeader'
import { StatusBadge } from '@/components/common/StatusBadge'
import { TextBlock } from '@/components/common/TextBlock'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Textarea } from '@/components/ui/input'
import type { ApplicationDetail } from '@/lib/api'
import { dates, fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import { useWithdrawApplication } from '../api/applications'
import { describeStageError } from '../lib/errors'
import { canWithdraw } from '../lib/workflow'
import { HistoryTimeline } from './HistoryTimeline'
import { ResumeButton } from './ResumeButton'
import { StageProgress } from './StageProgress'

/**
 * Candidate-safe rendering of an application: own status, history, cover letter, résumé and withdraw. Match scores,
 * internal notes, rejection reasons and staff identities are never requested nor shown (the API redacts them too).
 */
export function CandidateApplicationView({ application: a }: { application: ApplicationDetail }) {
  const withdraw = useWithdrawApplication()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')

  const confirm = () =>
    withdraw.mutate(
      { id: a.id, comment: reason },
      {
        onSuccess: () => {
          setOpen(false)
          setReason('')
          toast.success('Application withdrawn', { description: a.job_title })
        },
      },
    )
  const problem = withdraw.isError ? describeStageError(withdraw.error) : null

  return (
    <>
      <PageHeader
        title={a.job_title}
        description={a.company_name}
        breadcrumbs={[{ label: 'My applications', to: paths.applications }, { label: a.job_title }]}
        meta={<StatusBadge kind="application" status={a.status} />}
        actions={
          <>
            <Button asChild variant="outline">
              <Link to={paths.job(a.job_id)}>View job</Link>
            </Button>
            {canWithdraw(a.status) && (
              <Button
                variant="outline"
                onClick={() => {
                  withdraw.reset()
                  setOpen(true)
                }}
              >
                <Undo2 /> Withdraw
              </Button>
            )}
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Progress</CardTitle>
              <CardDescription>Updated {dates.relative(a.status_changed_at)}</CardDescription>
            </CardHeader>
            <CardContent>
              <StageProgress status={a.status} audience="candidate" />
            </CardContent>
          </Card>

          {a.cover_letter && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Your cover letter</CardTitle>
              </CardHeader>
              <CardContent>
                <TextBlock text={a.cover_letter} />
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">History</CardTitle>
            </CardHeader>
            <CardContent>
              <HistoryTimeline history={a.history} />
            </CardContent>
          </Card>
        </div>

        <aside aria-label="Application summary" className="space-y-6">
          <Card>
            <CardContent className="space-y-3 p-5 text-sm">
              <p className="flex items-center gap-2">
                <Building2 className="size-4 text-muted-foreground" aria-hidden /> {a.company_name}
              </p>
              <p className="flex items-center gap-2">
                <CalendarDays className="size-4 text-muted-foreground" aria-hidden /> Applied{' '}
                {dates.date(a.applied_at)}
              </p>
              <p className="text-muted-foreground">Source: {fmt.label(a.source)}</p>
              <ResumeButton resumeId={a.resume_id} filename={a.resume_filename} />
            </CardContent>
          </Card>
        </aside>
      </div>

      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Withdraw your application to “${a.job_title}”?`}
        description="The hiring team is told you are no longer interested. You can apply again later if the job is still open."
        confirmLabel="Withdraw application"
        destructive
        loading={withdraw.isPending}
        onConfirm={confirm}
      >
        <div className="space-y-3">
          {problem && (
            <Alert variant="danger" title={problem.title}>
              {problem.message}
            </Alert>
          )}
          <Field label="Reason" optional>
            <Textarea
              rows={3}
              maxLength={2000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Let the team know why (optional)"
            />
          </Field>
        </div>
      </ConfirmDialog>
    </>
  )
}
