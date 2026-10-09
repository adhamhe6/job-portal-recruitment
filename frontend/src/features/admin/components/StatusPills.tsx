import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { ACCOUNT_STATUS_LABELS, TASK_STATUS_LABELS } from '../lib/labels'
import type { TaskStatus } from '../api/types'

const dot = <span className="size-1.5 rounded-full bg-current" aria-hidden />

/** User / company status (ACTIVE | SUSPENDED): text + dot, never colour alone. */
export function AccountStatusBadge({ status, className }: { status: string; className?: string }) {
  const known = status in ACCOUNT_STATUS_LABELS
  return (
    <Badge
      variant={status === 'ACTIVE' ? 'success' : status === 'SUSPENDED' ? 'danger' : 'muted'}
      className={cn('gap-1.5', className)}
    >
      {dot}
      {known ? ACCOUNT_STATUS_LABELS[status as keyof typeof ACCOUNT_STATUS_LABELS] : status}
    </Badge>
  )
}

const TASK_VARIANT = {
  PENDING: 'muted',
  RUNNING: 'info',
  COMPLETED: 'success',
  FAILED: 'danger',
} as const

export function TaskStatusBadge({ status, className }: { status: TaskStatus; className?: string }) {
  return (
    <Badge variant={TASK_VARIANT[status] ?? 'muted'} className={cn('gap-1.5', className)}>
      {dot}
      {TASK_STATUS_LABELS[status] ?? status}
    </Badge>
  )
}
