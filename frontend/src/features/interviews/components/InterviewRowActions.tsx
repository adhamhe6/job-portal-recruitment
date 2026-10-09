import { CalendarClock, CheckCircle2, Eye, MoreHorizontal, UserX, XCircle } from 'lucide-react'
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
import { paths } from '@/routes/paths'
import type { StaffInterviewItem } from '../api/types'
import type { InterviewAction } from '../hooks/useInterviewActions'
import { interviewActions } from '../lib/stateMachine'

const NotStarted = () => <span className="ml-auto text-xs text-muted-foreground">Not started yet</span>

/** Per-row "⋯" menu: only the actions the state machine and the user's permissions allow. */
export function InterviewRowActions({
  interview,
  onAction,
}: {
  interview: StaffInterviewItem
  onAction: (interview: StaffInterviewItem, action: InterviewAction) => void
}) {
  const { can, user } = useAuth()
  const navigate = useNavigate()
  const actions = interviewActions({
    status: interview.status,
    startAt: interview.start_at,
    canManage: can('schedule_interviews'),
    isParticipant: interview.participants.some((p) => p.user_id === user?.id),
  })
  const label = `${interview.candidate_name} — ${interview.job_title}`

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Actions for interview with ${label}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-60">
        <DropdownMenuItem onSelect={() => navigate(paths.interview(interview.id))}>
          <Eye /> View details
        </DropdownMenuItem>
        {(actions.reschedule.allowed || actions.complete.allowed || actions.complete.reason) && (
          <DropdownMenuSeparator />
        )}
        {actions.reschedule.allowed && (
          <DropdownMenuItem onSelect={() => onAction(interview, 'reschedule')}>
            <CalendarClock /> Reschedule
          </DropdownMenuItem>
        )}
        {(actions.complete.allowed || actions.complete.reason) && (
          <>
            <DropdownMenuItem
              disabled={!actions.complete.allowed}
              title={actions.complete.reason}
              onSelect={() => onAction(interview, 'complete')}
            >
              <CheckCircle2 /> Mark completed
              {!actions.complete.allowed && <NotStarted />}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!actions.noShow.allowed}
              title={actions.noShow.reason}
              onSelect={() => onAction(interview, 'no-show')}
            >
              <UserX /> Record no-show
              {!actions.noShow.allowed && <NotStarted />}
            </DropdownMenuItem>
          </>
        )}
        {actions.cancel.allowed && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem destructive onSelect={() => onAction(interview, 'cancel')}>
              <XCircle /> Cancel interview
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
