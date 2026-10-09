import { zodResolver } from '@hookform/resolvers/zod'
import { Globe } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { ErrorState } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { MultiSelect, type ComboboxOption } from '@/components/ui/combobox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, NativeSelect, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useCompanyMembers } from '@/features/companies/api/companies'
import { ApiError, type MemberOut } from '@/lib/api'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import {
  useInterview,
  useScheduleInterview,
  useSchedulingContext,
  useUpdateInterview,
  type SchedulingContext,
} from '../api/interviews'
import type { StaffInterviewItem, StaffInterviewView } from '../api/types'
import { describeConflict, parseConflicts } from '../lib/conflicts'
import { INTERVIEW_TYPE_OPTIONS } from '../lib/labels'
import {
  endAfterStartChange,
  makeScheduleSchema,
  toCreatePayload,
  toUpdatePayload,
  type ScheduleFormValues,
} from '../lib/schedule'
import {
  formatSlot,
  instantToLocalInput,
  listTimeZones,
  offsetLabel,
  viewerTimeZone,
  wallTimeToInstant,
} from '../lib/time'

export interface ScheduleInterviewDialogProps {
  /** The application the interview belongs to (must be SHORTLISTED or INTERVIEW to schedule). */
  applicationId: string
  /** Pass an existing interview to reschedule / edit it instead of creating a new one. */
  interview?: StaffInterviewItem | StaffInterviewView
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called with the saved interview after a successful schedule / reschedule (the dialog closes itself). */
  onDone?: (interview: StaffInterviewView) => void
}

const SCHEDULABLE = ['SHORTLISTED', 'INTERVIEW']
const FORM_FIELDS = [
  'interview_type',
  'timezone',
  'start',
  'end',
  'location',
  'meeting_url',
  'notes',
  'interviewers',
  'observers',
] as const

/**
 * Schedule a new interview for an application, or reschedule / edit an existing one.
 *
 * - times are entered as wall-clock time in an explicit IANA timezone and previewed with the zone and UTC equivalent
 * - participants are company staff only (active recruiters and the job's hiring manager); at least one interviewer
 * - a 409 `INTERVIEW_CONFLICT` is shown with who is already booked and when, and the form stays open to adjust
 */
export function ScheduleInterviewDialog({
  applicationId,
  interview,
  open,
  onOpenChange,
  onDone,
}: ScheduleInterviewDialogProps) {
  const rescheduling = Boolean(interview)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>{rescheduling ? 'Reschedule interview' : 'Schedule interview'}</DialogTitle>
          <DialogDescription>
            {rescheduling
              ? 'Change the time or details. Moving the time asks the candidate to confirm again.'
              : 'Pick a time, add the interviewers and tell the candidate where to join.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody
          applicationId={applicationId}
          interview={interview}
          onClose={() => onOpenChange(false)}
          onDone={onDone}
        />
      </DialogContent>
    </Dialog>
  )
}

function FormSkeleton() {
  return (
    <div className="grid gap-4" role="status" aria-busy="true" aria-label="Loading scheduling details">
      <Skeleton className="h-9 w-full" />
      <div className="grid gap-4 sm:grid-cols-2">
        <Skeleton className="h-9" />
        <Skeleton className="h-9" />
      </div>
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  )
}

function DialogBody({
  applicationId,
  interview,
  onClose,
  onDone,
}: {
  applicationId: string
  interview?: StaffInterviewItem | StaffInterviewView
  onClose: () => void
  onDone?: (interview: StaffInterviewView) => void
}) {
  const ctx = useSchedulingContext(applicationId, true)
  const companyId = ctx.data?.application.company_id
  const members = useCompanyMembers(companyId)
  // The list shape has no internal notes; load the full record so saving never wipes them.
  const needsFull = Boolean(interview && !('notes' in interview))
  const full = useInterview(interview?.id, needsFull)
  const existing =
    interview && 'notes' in interview ? interview : (full.data as StaffInterviewView | undefined)

  const failed = ctx.isError ? ctx : members.isError ? members : full.isError ? full : null
  if (failed) {
    return (
      <ErrorState
        compact
        error={failed.error}
        onRetry={() => {
          void ctx.refetch()
          void members.refetch()
          if (needsFull) void full.refetch()
        }}
      />
    )
  }
  if (!ctx.data || !members.data || (interview && !existing)) return <FormSkeleton />

  return (
    <ScheduleForm
      applicationId={applicationId}
      context={ctx.data}
      members={members.data}
      existing={interview ? existing : undefined}
      onClose={onClose}
      onDone={onDone}
    />
  )
}

function memberName(m: Pick<MemberOut, 'first_name' | 'last_name'>) {
  return `${m.first_name} ${m.last_name}`.trim()
}

function ScheduleForm({
  applicationId,
  context,
  members,
  existing,
  onClose,
  onDone,
}: {
  applicationId: string
  context: SchedulingContext
  members: MemberOut[]
  existing?: StaffInterviewView
  onClose: () => void
  onDone?: (interview: StaffInterviewView) => void
}) {
  const { user } = useAuth()
  const { application, job } = context
  const schedule = useScheduleInterview()
  const update = useUpdateInterview(existing?.id ?? '')
  const pending = schedule.isPending || update.isPending

  // Eligible participants mirror the backend rules: active company staff; a hiring manager only for their own job.
  const eligible = useMemo(
    () =>
      members.filter(
        (m) =>
          m.status === 'ACTIVE' &&
          (m.role === 'RECRUITER' ||
            (m.role === 'HIRING_MANAGER' && (!job?.hiring_manager_id || job.hiring_manager_id === m.id))),
      ),
    [members, job],
  )

  const defaults = useMemo<ScheduleFormValues>(() => {
    if (existing) {
      const tz = existing.timezone
      return {
        interview_type: existing.interview_type,
        timezone: tz,
        start: instantToLocalInput(existing.start_at, tz),
        end: instantToLocalInput(existing.end_at, tz),
        location: existing.location ?? '',
        meeting_url: existing.meeting_url ?? '',
        notes: existing.notes ?? '',
        interviewers: existing.participants.filter((p) => p.role === 'INTERVIEWER').map((p) => p.user_id),
        observers: existing.participants.filter((p) => p.role === 'OBSERVER').map((p) => p.user_id),
      }
    }
    const me = user && eligible.some((m) => m.id === user.id) ? [user.id] : []
    return {
      interview_type: 'TECHNICAL',
      timezone: viewerTimeZone(),
      start: '',
      end: '',
      location: '',
      meeting_url: '',
      notes: '',
      interviewers: me,
      observers: [],
    }
  }, [existing, eligible, user])

  const schema = useMemo(
    () =>
      makeScheduleSchema({
        original: existing
          ? { start: defaults.start, end: defaults.end, timezone: defaults.timezone }
          : undefined,
      }),
    [existing, defaults],
  )

  const {
    register,
    handleSubmit,
    setError,
    setValue,
    getValues,
    control,
    formState: { errors },
  } = useForm<ScheduleFormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaults,
    mode: 'onTouched',
  })

  const values = useWatch({ control }) as ScheduleFormValues
  const [previousStart, setPreviousStart] = useState(defaults.start)
  const [formError, setFormError] = useState<string | null>(null)
  const [conflict, setConflict] = useState<{ key: string; lines: string[] } | null>(null)
  const slotKey = JSON.stringify([values.start, values.end, values.timezone, values.interviewers])
  const visibleConflict = conflict && conflict.key === slotKey ? conflict : null

  const zones = useMemo(() => listTimeZones([defaults.timezone]), [defaults.timezone])
  const options = useMemo<ComboboxOption[]>(() => {
    const byId = new Map<string, ComboboxOption>()
    for (const m of eligible) {
      byId.set(m.id, {
        value: m.id,
        label: memberName(m),
        description: [m.role === 'HIRING_MANAGER' ? 'Hiring manager' : 'Recruiter', m.job_title]
          .filter(Boolean)
          .join(' · '),
      })
    }
    // Keep people who are already on the interview selectable even if they are no longer eligible.
    for (const p of existing?.participants ?? []) {
      if (!byId.has(p.user_id)) byId.set(p.user_id, { value: p.user_id, label: p.name })
    }
    return [...byId.values()]
  }, [eligible, existing])

  const start = values.start && values.timezone ? wallTimeToInstant(values.start, values.timezone) : null
  const end = values.end && values.timezone ? wallTimeToInstant(values.end, values.timezone) : null
  const zoneKnown = Boolean(values.timezone)
  const stageBlocked = !existing && !SCHEDULABLE.includes(application.status)

  const onSubmit = handleSubmit(
    async (v) => {
      setFormError(null)
      setConflict(null)
      try {
        const saved = existing
          ? await update.mutateAsync(toUpdatePayload(v))
          : await schedule.mutateAsync(toCreatePayload(applicationId, v))
        toast.success(existing ? 'Interview updated' : 'Interview scheduled', {
          description: `${application.candidate_name} · ${formatSlot(saved.start_at, saved.end_at, saved.timezone)}`,
        })
        onDone?.(saved)
        onClose()
      } catch (e) {
        const clashes = parseConflicts(e)
        if (clashes) {
          setConflict({
            key: JSON.stringify([v.start, v.end, v.timezone, v.interviewers]),
            lines: clashes.length
              ? clashes.map((c) => describeConflict(c, v.timezone))
              : [e instanceof ApiError ? e.message : 'The chosen time is not available.'],
          })
          setError('start', { type: 'conflict', message: 'This time clashes with an existing interview' })
          focusFirstError()
          return
        }
        setFormError(
          applyApiErrors(e, setError, {
            fields: FORM_FIELDS,
            fieldMap: { participants: 'interviewers', start_at: 'start', end_at: 'end' },
            codeFields: {
              INTERVIEWER_REQUIRED: 'interviewers',
              INVALID_PARTICIPANT: 'interviewers',
              DUPLICATE_PARTICIPANT: 'interviewers',
              INVALID_TIME_RANGE: 'end',
              INTERVIEW_TOO_LONG: 'end',
              INTERVIEW_IN_PAST: 'start',
              LOCATION_OR_LINK_REQUIRED: 'location',
            },
          }),
        )
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  const timeChanged =
    Boolean(existing) &&
    (values.start !== defaults.start || values.end !== defaults.end || values.timezone !== defaults.timezone)
  const submitLabel = !existing ? 'Schedule interview' : timeChanged ? 'Reschedule interview' : 'Save changes'

  return (
    <form onSubmit={onSubmit} noValidate className="grid gap-5">
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{application.candidate_name}</span> ·{' '}
        {application.job_title}
      </p>

      {stageBlocked && (
        <Alert variant="warning" title="This application cannot be scheduled yet">
          Interviews can only be scheduled for shortlisted applications or applications already at the
          interview stage. This one is currently <strong>{application.status.toLowerCase()}</strong>.
        </Alert>
      )}

      {visibleConflict && (
        <Alert variant="danger" title="Time conflict: someone is already booked">
          <ul>
            {visibleConflict.lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <p className="mt-1">Choose another time, or change the interviewers, then try again.</p>
        </Alert>
      )}
      {formError && <Alert variant="danger">{formError}</Alert>}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Interview type" required error={errors.interview_type?.message}>
          <NativeSelect {...register('interview_type')}>
            {INTERVIEW_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field
          label="Timezone"
          required
          error={errors.timezone?.message}
          hint="The zone the candidate is told."
        >
          <NativeSelect {...register('timezone')}>
            {zones.map((z) => (
              <option key={z} value={z}>
                {z.replace(/_/g, ' ')}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Starts" required error={errors.start?.message}>
          <Input
            type="datetime-local"
            {...register('start', {
              onChange: (e: { target: { value: string } }) => {
                const next = e.target.value
                // Moving the start keeps the interview's duration (60 minutes for a new one).
                if (next) setValue('end', endAfterStartChange(previousStart, getValues('end'), next))
                setPreviousStart(next)
              },
            })}
          />
        </Field>
        <Field label="Ends" required error={errors.end?.message}>
          <Input type="datetime-local" {...register('end')} />
        </Field>
      </div>

      {zoneKnown && start && end && (
        <p
          className="-mt-2 flex items-start gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs text-muted-foreground"
          aria-live="polite"
        >
          <Globe className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            {formatSlot(start.toISOString(), end.toISOString(), values.timezone)} (
            {offsetLabel(start, values.timezone)})
            {values.timezone !== 'UTC' && <> = {formatSlot(start.toISOString(), end.toISOString(), 'UTC')}</>}
          </span>
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Location"
          error={errors.location?.message}
          hint="Address or room. Optional if you add a link."
        >
          <Input placeholder="e.g. HQ, 3rd floor, Room Bergen" maxLength={300} {...register('location')} />
        </Field>
        <Field
          label="Meeting link"
          error={errors.meeting_url?.message}
          hint="Video-call link, https:// only. Optional if you add a location."
        >
          <Input
            type="url"
            inputMode="url"
            placeholder="https://meet.example.com/…"
            {...register('meeting_url')}
          />
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Controller
          control={control}
          name="interviewers"
          render={({ field }) => (
            <Field label="Interviewers" required error={errors.interviewers?.message as string | undefined}>
              <MultiSelect
                values={field.value}
                onChange={field.onChange}
                options={options.map((o) => ({ ...o, disabled: values.observers.includes(o.value) }))}
                placeholder="Choose interviewers"
                searchPlaceholder="Search your team…"
                emptyText="No matching team members."
              />
            </Field>
          )}
        />
        <Controller
          control={control}
          name="observers"
          render={({ field }) => (
            <Field label="Observers" optional error={errors.observers?.message as string | undefined}>
              <MultiSelect
                values={field.value}
                onChange={field.onChange}
                options={options.map((o) => ({ ...o, disabled: values.interviewers.includes(o.value) }))}
                placeholder="Add observers"
                searchPlaceholder="Search your team…"
                emptyText="No matching team members."
              />
            </Field>
          )}
        />
      </div>
      <p className="-mt-3 text-xs text-muted-foreground">
        Only active recruiters and the job&apos;s hiring manager can take part. Observers do not block their
        calendar.
      </p>

      <Field
        label="Internal notes"
        optional
        error={errors.notes?.message}
        hint="Visible to the hiring team only, never to the candidate."
      >
        <Textarea rows={3} maxLength={4000} {...register('notes')} />
      </Field>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" loading={pending} disabled={stageBlocked}>
          {submitLabel}
        </Button>
      </DialogFooter>
    </form>
  )
}
