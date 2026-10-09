import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Alert } from '@/components/ui/alert'
import { Field } from '@/components/ui/field'
import { Textarea } from '@/components/ui/input'
import { ApiError, errorMessage, type JobStatus } from '@/lib/api'
import { JOB_STATUS_LABELS } from '@/lib/enums'
import { paths } from '@/routes/paths'
import { useDeleteJob, useJobTransition } from '../api/jobs'
import { ACTIONS, type LifecycleAction } from '../lib/lifecycle'

export interface LifecycleJob {
  id: string
  title: string
}

type Pending = { job: LifecycleJob; action: LifecycleAction | 'delete' }

/** Plain-language explanation for lifecycle failures. */
export function describeLifecycleError(error: unknown): {
  title?: string
  message: string
  problems?: string[]
} {
  if (error instanceof ApiError) {
    if (error.code === 'INVALID_STATE_TRANSITION') {
      const d = (error.details ?? {}) as { from?: JobStatus; to?: JobStatus }
      const from = d.from ? JOB_STATUS_LABELS[d.from]?.toLowerCase() : null
      const to = d.to ? JOB_STATUS_LABELS[d.to]?.toLowerCase() : null
      return {
        title: "That change isn't possible right now",
        message:
          from && to
            ? `This job is currently ${from}, so it can't become ${to}. Someone may have just changed it — refresh the page and check its current status.`
            : error.message,
      }
    }
    if (error.code === 'PUBLISH_VALIDATION_FAILED') {
      return {
        title: "This job can't be published yet",
        message: 'Fix the following, then try again:',
        problems: error.detailMessages,
      }
    }
    if (error.code === 'JOB_NOT_DELETABLE') {
      return { message: 'Only drafts can be deleted. Close and archive a published job instead.' }
    }
    if (error.status === 403 || error.status === 404)
      return { message: 'You no longer have access to this job, or it has been removed.' }
  }
  return { message: errorMessage(error) }
}

/**
 * Lifecycle confirmations (publish / pause / resume / close / archive / delete draft).
 *
 *   const { request, dialog } = useJobLifecycle({ onDone })
 *   <Button onClick={() => request(job, 'close')}>Close</Button>   …   {dialog}
 *
 * The dialog stays open on failure and explains why (INVALID_STATE_TRANSITION, PUBLISH_VALIDATION_FAILED, …).
 */
export function useJobLifecycle({
  onDone,
}: { onDone?: (job: LifecycleJob, action: LifecycleAction | 'delete') => void } = {}): {
  request: (job: LifecycleJob, action: LifecycleAction | 'delete') => void
  dialog: ReactNode
  pending: boolean
} {
  const transition = useJobTransition()
  const remove = useDeleteJob()
  const [state, setState] = useState<Pending | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<unknown>(null)
  const busy = transition.isPending || remove.isPending

  const close = () => {
    setState(null)
    setReason('')
    setError(null)
    transition.reset()
    remove.reset()
  }

  const confirm = async () => {
    if (!state) return
    setError(null)
    const { job, action } = state
    try {
      if (action === 'delete') {
        await remove.mutateAsync(job.id)
        toast.success('Draft deleted')
      } else {
        await transition.mutateAsync({ id: job.id, action, reason })
        toast.success(ACTIONS[action].success, { description: job.title })
      }
      const done = state
      close()
      onDone?.(done.job, done.action)
    } catch (e) {
      setError(e)
    }
  }

  let dialog: ReactNode = null
  if (state) {
    const def = state.action === 'delete' ? null : ACTIONS[state.action]
    const isDelete = def === null
    const problem = error ? describeLifecycleError(error) : null
    dialog = (
      <ConfirmDialog
        open
        onOpenChange={(o) => !o && close()}
        title={isDelete ? `Delete draft “${state.job.title}”?` : def.title(state.job.title)}
        description={
          isDelete ? 'This draft will be permanently deleted. This cannot be undone.' : def.description
        }
        confirmLabel={isDelete ? 'Delete draft' : def.confirmLabel}
        destructive={isDelete || def?.destructive}
        loading={busy}
        onConfirm={confirm}
      >
        {!isDelete && def?.askReason && (
          <Field label="Reason" optional hint="Recorded in the job's audit trail.">
            <Textarea rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        )}
        {problem && (
          <Alert
            variant={
              error instanceof ApiError && error.code === 'PUBLISH_VALIDATION_FAILED' ? 'warning' : 'danger'
            }
            title={problem.title}
          >
            {problem.message}
            {problem.problems && problem.problems.length > 0 && (
              <ul>
                {problem.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}
            {error instanceof ApiError && error.code === 'PUBLISH_VALIDATION_FAILED' && (
              <p className="mt-1">
                <Link to={paths.manageJobEdit(state.job.id)}>Edit this job</Link>
              </p>
            )}
          </Alert>
        )}
      </ConfirmDialog>
    )
  }

  return { request: (job, action) => setState({ job, action }), dialog, pending: busy }
}
