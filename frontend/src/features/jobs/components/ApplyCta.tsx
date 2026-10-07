import { CheckCircle2, LogIn, Send } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { JobDetail, JobPublic } from '@/lib/api'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import type { ApplicationStatus } from '@/lib/api'
import { loginUrl, paths } from '@/routes/paths'
import { ApplyDialog } from './ApplyDialog'

/**
 * The apply call-to-action, in every state:
 *  - visitor            -> "Sign in to apply" (returns to this job afterwards)
 *  - candidate, open    -> "Apply now" (opens the apply dialog)
 *  - candidate, applied -> status + link to the application
 *  - candidate, blocked -> disabled button + the API's reason (closed / deadline passed)
 *  - staff / admin      -> nothing
 */
export function ApplyCta({
  job,
  className,
  compact,
}: {
  job: JobPublic | JobDetail
  className?: string
  compact?: boolean
}) {
  const { status, isCandidate } = useAuth()
  const location = useLocation()
  const [open, setOpen] = useState(false)

  if (status !== 'authenticated') {
    return (
      <Button asChild size="lg" className={className}>
        <Link to={loginUrl(location.pathname + location.search)}>
          <LogIn /> Sign in to apply
        </Link>
      </Button>
    )
  }
  if (!isCandidate) return null

  if (job.my_application_id) {
    const label =
      APPLICATION_STATUS_LABELS[(job.my_application_status ?? 'APPLIED') as ApplicationStatus] ??
      job.my_application_status
    return compact ? (
      <Button asChild variant="soft" size="lg" className={className}>
        <Link to={paths.application(job.my_application_id)}>
          <CheckCircle2 /> Applied · {label}
        </Link>
      </Button>
    ) : (
      <Alert variant="success" title={`You applied · ${label}`} className={className}>
        <Link to={paths.application(job.my_application_id)}>View your application</Link>
      </Alert>
    )
  }

  const blocked = job.can_apply === false
  return (
    <div className={className}>
      <Button size="lg" className="w-full" disabled={blocked} onClick={() => setOpen(true)}>
        <Send /> Apply now
      </Button>
      {blocked && !compact && (
        <p className="mt-2 text-center text-sm text-muted-foreground">
          {job.apply_blocked_reason ?? 'This job is not accepting applications.'}
        </p>
      )}
      <ApplyDialog job={job} open={open} onOpenChange={setOpen} />
    </div>
  )
}
