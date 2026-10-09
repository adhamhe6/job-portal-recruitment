import { CalendarPlus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { paths } from '@/routes/paths'
import { useSchedulableApplications } from '../api/interviews'
import type { StaffInterviewView } from '../api/types'
import { ScheduleInterviewDialog } from './ScheduleInterviewDialog'

function ApplicationPicker({ onPick }: { onPick: (applicationId: string) => void }) {
  const [search, setSearch] = useState('')
  const q = useDebouncedValue(search, 250)
  const apps = useSchedulableApplications(q, true)

  if (apps.isError && !apps.data) return <ErrorState compact error={apps.error} onRetry={() => apps.refetch()} />
  if (apps.data && apps.data.items.length === 0 && !q) {
    return (
      <EmptyState
        compact
        icon={<CalendarPlus aria-hidden />}
        title="No applications are ready to interview"
        description="Interviews can be scheduled for shortlisted candidates. Shortlist an application first."
        action={
          <Button asChild variant="outline">
            <Link to={paths.applications}>Go to applications</Link>
          </Button>
        }
      />
    )
  }
  return (
    <Field label="Application" required hint="Shortlisted candidates and candidates already at the interview stage.">
      <Combobox
        value=""
        onChange={onPick}
        placeholder="Search candidates or jobs"
        searchPlaceholder="Search by candidate or job…"
        emptyText="No matching applications."
        loading={apps.isFetching}
        onSearchChange={setSearch}
        options={(apps.data?.items ?? []).map((a) => ({
          value: a.id,
          label: `${a.candidate_name} — ${a.job_title}`,
          description: APPLICATION_STATUS_LABELS[a.status],
        }))}
      />
    </Field>
  )
}

/**
 * "Schedule interview" for pages that are not tied to one application: pick a shortlisted application, then the
 * schedule dialog opens for it.
 */
export function NewInterviewButton({
  onDone,
  variant = 'default',
}: {
  onDone?: (interview: StaffInterviewView) => void
  variant?: 'default' | 'outline'
}) {
  const [picking, setPicking] = useState(false)
  const [applicationId, setApplicationId] = useState<string | null>(null)
  return (
    <>
      <Button variant={variant} onClick={() => setPicking(true)}>
        <CalendarPlus /> Schedule interview
      </Button>
      <Dialog open={picking} onOpenChange={setPicking}>
        <DialogContent size="md">
          <DialogHeader>
            <DialogTitle>Schedule an interview</DialogTitle>
            <DialogDescription>Choose the application you want to interview for.</DialogDescription>
          </DialogHeader>
          {picking && (
            <ApplicationPicker
              onPick={(id) => {
                setPicking(false)
                setApplicationId(id)
              }}
            />
          )}
        </DialogContent>
      </Dialog>
      {applicationId && (
        <ScheduleInterviewDialog
          applicationId={applicationId}
          open
          onOpenChange={(o) => !o && setApplicationId(null)}
          onDone={onDone}
        />
      )}
    </>
  )
}
