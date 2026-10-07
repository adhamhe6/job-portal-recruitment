import { Badge, type BadgeProps } from '@/components/ui/badge'
import { APPLICATION_STATUS_LABELS, JOB_STATUS_LABELS } from '@/lib/enums'
import { fmt } from '@/lib/format'
import { cn } from '@/lib/utils'

type Variant = NonNullable<BadgeProps['variant']>
interface Def {
  label: string
  variant: Variant
}

const JOB: Record<string, Def> = {
  DRAFT: { label: JOB_STATUS_LABELS.DRAFT, variant: 'muted' },
  PUBLISHED: { label: JOB_STATUS_LABELS.PUBLISHED, variant: 'success' },
  PAUSED: { label: JOB_STATUS_LABELS.PAUSED, variant: 'warning' },
  CLOSED: { label: JOB_STATUS_LABELS.CLOSED, variant: 'orange' },
  ARCHIVED: { label: JOB_STATUS_LABELS.ARCHIVED, variant: 'secondary' },
}
const APPLICATION: Record<string, Def> = {
  APPLIED: { label: APPLICATION_STATUS_LABELS.APPLIED, variant: 'info' },
  SCREENING: { label: APPLICATION_STATUS_LABELS.SCREENING, variant: 'violet' },
  SHORTLISTED: { label: APPLICATION_STATUS_LABELS.SHORTLISTED, variant: 'default' },
  INTERVIEW: { label: APPLICATION_STATUS_LABELS.INTERVIEW, variant: 'warning' },
  OFFER: { label: APPLICATION_STATUS_LABELS.OFFER, variant: 'orange' },
  HIRED: { label: APPLICATION_STATUS_LABELS.HIRED, variant: 'success' },
  REJECTED: { label: APPLICATION_STATUS_LABELS.REJECTED, variant: 'danger' },
  WITHDRAWN: { label: APPLICATION_STATUS_LABELS.WITHDRAWN, variant: 'muted' },
}
const RESUME: Record<string, Def> = {
  UPLOADED: { label: 'Uploaded', variant: 'muted' },
  PROCESSING: { label: 'Processing', variant: 'info' },
  PROCESSED: { label: 'Processed', variant: 'success' },
  FAILED: { label: 'Failed', variant: 'danger' },
}
const INTERVIEW: Record<string, Def> = {
  SCHEDULED: { label: 'Scheduled', variant: 'info' },
  CONFIRMED: { label: 'Confirmed', variant: 'success' },
  RESCHEDULED: { label: 'Rescheduled', variant: 'warning' },
  COMPLETED: { label: 'Completed', variant: 'secondary' },
  CANCELLED: { label: 'Cancelled', variant: 'muted' },
  NO_SHOW: { label: 'No-show', variant: 'danger' },
}

const TABLES = { job: JOB, application: APPLICATION, resume: RESUME, interview: INTERVIEW }
export type StatusKind = keyof typeof TABLES

/**
 * Status pill for the four lifecycles. Always text + a dot (never colour alone). Unknown values degrade to a
 * neutral label so a new backend status never breaks the UI.
 *
 *   <StatusBadge kind="job" status={job.status} />
 */
export function StatusBadge({ kind, status, className }: { kind: StatusKind; status: string; className?: string }) {
  const def = TABLES[kind][status] ?? { label: fmt.label(status), variant: 'muted' as Variant }
  return (
    <Badge variant={def.variant} className={cn('gap-1.5', className)}>
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {def.label}
    </Badge>
  )
}
