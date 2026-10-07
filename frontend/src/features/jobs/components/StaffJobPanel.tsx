import { Eye, Pencil, Target, Trash2, Users } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { JobDetail } from '@/lib/api'
import { fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import { useJobLifecycle } from '../hooks/useJobLifecycle'
import { ACTIONS, availableActions, EDITABLE_STATUSES } from '../lib/lifecycle'

const STATUS_NOTES: Partial<Record<JobDetail['status'], { variant: 'info' | 'warning'; text: string }>> = {
  DRAFT: { variant: 'info', text: 'This job is a draft and not visible to candidates. Publish it when it is ready.' },
  PAUSED: { variant: 'warning', text: 'This job is paused: hidden from search and not accepting applications.' },
  CLOSED: { variant: 'warning', text: 'This job is closed. It no longer accepts applications.' },
  ARCHIVED: { variant: 'info', text: 'This job is archived and read-only.' },
}

/** What staff of the owning company see on top of the public job page: status, lifecycle actions, shortcuts. */
export function StaffJobPanel({ job }: { job: JobDetail }) {
  const { can } = useAuth()
  const navigate = useNavigate()
  const canManage = can('manage_jobs')
  const { request, dialog } = useJobLifecycle({ onDone: (_j, action) => action === 'delete' && navigate(paths.manageJobs) })
  const actions = canManage ? availableActions(job.status, job.allowed_transitions) : []
  const note = STATUS_NOTES[job.status]
  const editable = canManage && EDITABLE_STATUSES.includes(job.status)

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2">
            <Eye className="size-4 text-muted-foreground" aria-hidden /> Staff view
          </CardTitle>
          <CardDescription>Only people at {job.company.name} can see this panel.</CardDescription>
        </div>
        <StatusBadge kind="job" status={job.status} />
      </CardHeader>
      <CardContent className="space-y-4">
        {note && <Alert variant={note.variant}>{note.text}</Alert>}
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-muted-foreground">Applications</dt>
            <dd className="text-lg font-semibold tabular">{fmt.int(job.application_count)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Hiring manager</dt>
            <dd className="font-medium">{job.hiring_manager_name ?? 'Unassigned'}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Matching</dt>
            <dd className="font-medium">{job.embedding_ready ? 'Ready' : 'Pending'}</dd>
          </div>
        </dl>
        <div className="flex flex-wrap gap-2">
          {editable && (
            <Button asChild variant="outline">
              <Link to={paths.manageJobEdit(job.id)}>
                <Pencil /> Edit job
              </Link>
            </Button>
          )}
          {actions.map((a) => {
            const def = ACTIONS[a]
            const Icon = def.icon
            return (
              <Button key={a} variant={a === 'publish' ? 'default' : def.destructive ? 'outline' : 'secondary'} onClick={() => request(job, a)}>
                <Icon /> {def.label}
              </Button>
            )
          })}
          {canManage && job.status === 'DRAFT' && (
            <Button variant="ghost" className="text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={() => request(job, 'delete')}>
              <Trash2 /> Delete draft
            </Button>
          )}
          <span className="hidden flex-1 sm:block" />
          <Button asChild variant="ghost">
            <Link to={`${paths.applications}?job_id=${job.id}`}>
              <Users /> Applications ({fmt.int(job.application_count)})
            </Link>
          </Button>
          <Button asChild variant="ghost">
            <Link to={paths.matchingJob(job.id)}>
              <Target /> Candidate matching
            </Link>
          </Button>
        </div>
        {job.status === 'PUBLISHED' && editable && <p className="text-xs text-muted-foreground">Edits to a published job go live immediately and refresh candidate matches in the background.</p>}
      </CardContent>
      {dialog}
    </Card>
  )
}
