import { Eye, MoreHorizontal, Pencil, Target, Trash2, Users } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { JobListItem } from '@/lib/api'
import { paths } from '@/routes/paths'
import { ACTIONS, availableActions, EDITABLE_STATUSES, type LifecycleAction } from '../lib/lifecycle'

/** Per-row "⋯" menu on the jobs list: navigation shortcuts + lifecycle actions (permission- and status-aware). */
export function JobRowActions({
  job,
  onAction,
}: {
  job: Pick<JobListItem, 'id' | 'title' | 'status'>
  onAction: (job: { id: string; title: string }, action: LifecycleAction | 'delete') => void
}) {
  const { can } = useAuth()
  const navigate = useNavigate()
  const canManage = can('manage_jobs')
  const lifecycle = canManage ? availableActions(job.status) : []
  const editable = canManage && EDITABLE_STATUSES.includes(job.status)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${job.title}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56">
        <DropdownMenuItem onSelect={() => navigate(paths.job(job.id))}>
          <Eye /> View job
        </DropdownMenuItem>
        {editable && (
          <DropdownMenuItem onSelect={() => navigate(paths.manageJobEdit(job.id))}>
            <Pencil /> Edit
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => navigate(`${paths.applications}?job_id=${job.id}`)}>
          <Users /> Applications
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate(paths.matchingJob(job.id))}>
          <Target /> Candidate matching
        </DropdownMenuItem>
        {(lifecycle.length > 0 || (canManage && job.status === 'DRAFT')) && <DropdownMenuSeparator />}
        {lifecycle.map((a) => {
          const def = ACTIONS[a]
          const Icon = def.icon
          return (
            <DropdownMenuItem
              key={a}
              destructive={def.destructive && a !== 'close'}
              onSelect={() => onAction(job, a)}
            >
              <Icon /> {def.label}
            </DropdownMenuItem>
          )
        })}
        {canManage && job.status === 'DRAFT' && (
          <DropdownMenuItem destructive onSelect={() => onAction(job, 'delete')}>
            <Trash2 /> Delete draft
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
