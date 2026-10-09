import { Alert } from '@/components/ui/alert'
import { Stepper } from '@/components/common/Stepper'
import type { ApplicationStatus } from '@/lib/api'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { PIPELINE_STAGES } from '../lib/workflow'

const STEPS = PIPELINE_STAGES.map((s) => ({ id: s, label: APPLICATION_STATUS_LABELS[s] }))

/** Where the application is in the hiring pipeline; rejected/withdrawn applications get an explicit notice instead. */
export function StageProgress({
  status,
  audience,
}: {
  status: ApplicationStatus
  audience: 'staff' | 'candidate'
}) {
  if (status === 'REJECTED')
    return (
      <Alert variant="danger" title="Not moving forward">
        {audience === 'candidate'
          ? 'The hiring team decided not to proceed with this application.'
          : 'This application was rejected. Rejected applications cannot be reopened.'}
      </Alert>
    )
  if (status === 'WITHDRAWN')
    return (
      <Alert variant="info" title="Withdrawn">
        {audience === 'candidate'
          ? 'You withdrew this application.'
          : 'The candidate withdrew this application.'}
      </Alert>
    )
  return (
    <div className="overflow-x-auto pb-1">
      <Stepper className="min-w-[22rem]" steps={STEPS} current={PIPELINE_STAGES.indexOf(status)} />
    </div>
  )
}
