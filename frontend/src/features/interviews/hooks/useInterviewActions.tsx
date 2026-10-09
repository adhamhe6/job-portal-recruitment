import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Alert } from '@/components/ui/alert'
import { Field } from '@/components/ui/field'
import { Textarea } from '@/components/ui/input'
import { ApiError, errorMessage } from '@/lib/api'
import { useInterviewTransition } from '../api/interviews'
import type { StaffInterviewItem, StaffInterviewView } from '../api/types'
import { ScheduleInterviewDialog } from '../components/ScheduleInterviewDialog'
import { interviewTypeLabel } from '../lib/labels'
import { formatSlot } from '../lib/time'

export type InterviewAction = 'reschedule' | 'cancel' | 'complete' | 'no-show'
type Target = StaffInterviewItem | StaffInterviewView

const COPY: Record<
  Exclude<InterviewAction, 'reschedule'>,
  { title: string; confirm: string; done: string; destructive?: boolean; body: (who: string) => string }
> = {
  cancel: {
    title: 'Cancel this interview?',
    confirm: 'Cancel interview',
    done: 'Interview cancelled',
    destructive: true,
    body: (who) =>
      `${who} and the interviewers are notified and the time slot is freed. The reason below is internal and is not sent to the candidate.`,
  },
  complete: {
    title: 'Mark as completed?',
    confirm: 'Mark completed',
    done: 'Interview marked as completed',
    body: (who) => `The interview with ${who} took place. Interviewers can then add their feedback.`,
  },
  'no-show': {
    title: 'Record a no-show?',
    confirm: 'Record no-show',
    done: 'No-show recorded',
    destructive: true,
    body: (who) =>
      `${who} did not attend. The application's stage is not changed automatically — decide the next step on the application.`,
  },
}

/** Plain-language message for a failed interview action (keeps the explanation next to the retry). */
export function describeTransitionError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.isNetworkError) return e.message
    if (e.status === 404) return 'This interview no longer exists or you no longer have access to it.'
    if (e.status === 403) return 'You are not allowed to change this interview.'
    if (e.is('INVALID_STATE_TRANSITION')) return `${e.message}. Reload the page to see its current status.`
    return e.message
  }
  return errorMessage(e)
}

function TransitionDialog({
  target,
  action,
  onClose,
  onChanged,
}: {
  target: Target
  action: Exclude<InterviewAction, 'reschedule'>
  onClose: () => void
  onChanged?: (interview: StaffInterviewView) => void
}) {
  const copy = COPY[action]
  const transition = useInterviewTransition()
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const reasonTooShort = action === 'cancel' && reason.trim().length < 3

  const run = async () => {
    if (reasonTooShort) {
      setError('Give a reason of at least 3 characters.')
      return
    }
    setError(null)
    try {
      const iv = await transition.mutateAsync({
        id: target.id,
        action,
        reason: action === 'cancel' ? reason.trim() : undefined,
      })
      toast.success(copy.done, {
        description: `${target.candidate_name} · ${formatSlot(target.start_at, target.end_at, target.timezone)}`,
      })
      onChanged?.(iv as StaffInterviewView)
      onClose()
    } catch (e) {
      setError(describeTransitionError(e))
    }
  }

  return (
    <ConfirmDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={copy.title}
      description={
        <>
          <p className="font-medium text-foreground">
            {interviewTypeLabel(target.interview_type)} · {target.candidate_name}
          </p>
          <p className="mt-1">{copy.body(target.candidate_name)}</p>
        </>
      }
      confirmLabel={copy.confirm}
      cancelLabel="Keep as is"
      destructive={copy.destructive}
      loading={transition.isPending}
      onConfirm={run}
    >
      {action === 'cancel' && (
        <Field
          label="Reason"
          required
          hint="Internal. At least 3 characters."
          error={error && reasonTooShort ? error : undefined}
        >
          <Textarea
            rows={3}
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Interviewer unavailable; we will propose a new time"
          />
        </Field>
      )}
      {error && !(action === 'cancel' && reasonTooShort) && <Alert variant="danger">{error}</Alert>}
    </ConfirmDialog>
  )
}

/**
 * Reschedule / cancel / complete / no-show with their dialogs, shared by the interviews list and detail pages.
 *
 *   const { request, dialog } = useInterviewActions()
 *   <Button onClick={() => request(interview, 'cancel')}>Cancel</Button>   {dialog}
 */
export function useInterviewActions(onChanged?: (interview: StaffInterviewView) => void): {
  request: (interview: Target, action: InterviewAction) => void
  dialog: ReactNode
} {
  const [pending, setPending] = useState<{ target: Target; action: InterviewAction } | null>(null)
  const close = () => setPending(null)
  const dialog = pending ? (
    pending.action === 'reschedule' ? (
      <ScheduleInterviewDialog
        applicationId={pending.target.application_id}
        interview={pending.target}
        open
        onOpenChange={(o) => !o && close()}
        onDone={onChanged}
      />
    ) : (
      <TransitionDialog
        key={`${pending.target.id}:${pending.action}`}
        target={pending.target}
        action={pending.action}
        onClose={close}
        onChanged={onChanged}
      />
    )
  ) : null
  return { request: (target, action) => setPending({ target, action }), dialog }
}
