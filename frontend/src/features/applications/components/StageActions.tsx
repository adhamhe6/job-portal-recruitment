import { ArrowRight, Ban } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ApplicationDetail } from '@/lib/api'
import { useStatusChange } from '../hooks/useStatusChange'
import { moveLabel, staffTargets } from '../lib/workflow'

/** Workflow buttons for staff: the single forward step plus "Reject". Hidden/explained when the stage is final. */
export function StageActions({ application }: { application: ApplicationDetail }) {
  const { request, dialog, pendingId } = useStatusChange()
  const targets = staffTargets(application.status, application.allowed_next_statuses)
  const forward = targets.filter((t) => t !== 'REJECTED')
  const busy = pendingId === application.id

  if (targets.length === 0) return null
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {forward.map((t) => (
          <Button key={t} disabled={busy} onClick={() => request(application, t)}>
            <ArrowRight /> {moveLabel(t)}
          </Button>
        ))}
        {targets.includes('REJECTED') && (
          <Button variant="outline" disabled={busy} onClick={() => request(application, 'REJECTED')}>
            <Ban /> Reject
          </Button>
        )}
      </div>
      {dialog}
    </>
  )
}
