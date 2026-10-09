import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Alert } from '@/components/ui/alert'
import { Field } from '@/components/ui/field'
import { Textarea } from '@/components/ui/input'
import type { ApplicationStatus } from '@/lib/api'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { useChangeStatus } from '../api/applications'
import { describeStageError } from '../lib/errors'
import { asksForReason } from '../lib/workflow'

export interface MovableApplication {
  id: string
  candidate_name: string
  status: ApplicationStatus
}

/**
 * Move an application to another stage.
 *
 *   const { request, dialog, pendingId } = useStatusChange()
 *   <Button onClick={() => request(application, 'SHORTLISTED')} />   …   {dialog}
 *
 * Rejections open a confirmation with an optional reason; every other move is applied at once (optimistically) and
 * reports the outcome with a toast, rolling back when the server refuses.
 */
export function useStatusChange(): {
  request: (application: MovableApplication, target: ApplicationStatus) => void
  dialog: ReactNode
  pendingId: string | null
} {
  const mutation = useChangeStatus()
  const [pending, setPending] = useState<{ app: MovableApplication; target: ApplicationStatus } | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<unknown>(null)

  const close = () => {
    setPending(null)
    setReason('')
    setError(null)
  }

  const run = (app: MovableApplication, target: ApplicationStatus, comment?: string) =>
    mutation.mutateAsync({ id: app.id, status: target, comment }).then(() => {
      toast.success(`${app.candidate_name} moved to ${APPLICATION_STATUS_LABELS[target]}`)
    })

  const request = (app: MovableApplication, target: ApplicationStatus) => {
    if (asksForReason(target)) {
      setError(null)
      setPending({ app, target })
      return
    }
    run(app, target).catch((e: unknown) => {
      const d = describeStageError(e)
      toast.error(d.title, { description: d.message })
    })
  }

  const confirm = async () => {
    if (!pending) return
    setError(null)
    try {
      await run(pending.app, pending.target, reason)
      close()
    } catch (e) {
      setError(e)
    }
  }

  const problem = error ? describeStageError(error) : null
  const dialog = pending ? (
    <ConfirmDialog
      open
      onOpenChange={(o) => !o && close()}
      title={`Reject ${pending.app.candidate_name}?`}
      description="The candidate is notified that the team decided not to proceed. Rejected applications cannot be reopened."
      confirmLabel="Reject application"
      destructive
      loading={mutation.isPending}
      onConfirm={() => void confirm()}
    >
      <div className="space-y-3">
        {problem && (
          <Alert variant="danger" title={problem.title}>
            {problem.message}
          </Alert>
        )}
        <Field
          label="Reason"
          optional
          hint="Kept in the audit history for your team; not shown to the candidate."
        >
          <Textarea
            rows={3}
            maxLength={2000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Not enough experience with distributed systems"
          />
        </Field>
      </div>
    </ConfirmDialog>
  ) : null

  return {
    request,
    dialog,
    pendingId: mutation.isPending ? (mutation.variables?.id ?? null) : null,
  }
}
