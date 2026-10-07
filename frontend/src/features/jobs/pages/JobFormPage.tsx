import { zodResolver } from '@hookform/resolvers/zod'
import { Eye, Rocket, Save } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useForm, useWatch, type SubmitErrorHandler } from 'react-hook-form'
import { Link, useBlocker, useLocation, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageHeader } from '@/components/common/PageHeader'
import { ErrorState } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input, NativeSelect, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useCompanyMembers } from '@/features/companies/api/companies'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { ApiError, type JobDetail } from '@/lib/api'
import {
  CURRENCIES,
  EDUCATION_LEVEL_OPTIONS,
  EMPLOYMENT_TYPE_OPTIONS,
  EXPERIENCE_LEVEL_OPTIONS,
  JOB_STATUS_LABELS,
  ROLE_LABELS,
  WORKPLACE_TYPE_OPTIONS,
} from '@/lib/enums'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { dates } from '@/lib/format'
import { paths } from '@/routes/paths'
import { isStaffView, useCreateJob, useJob, useJobTransition, useUpdateJob } from '../api/jobs'
import { SkillsEditor } from '../components/SkillsEditor'
import { describeLifecycleError } from '../hooks/useJobLifecycle'
import {
  buildJobSchema,
  EMPTY_JOB_FORM,
  formValuesToPayload,
  JOB_ERROR_CODE_FIELDS,
  JOB_FORM_FIELDS,
  inferJobField,
  jobToFormValues,
  publishProblems,
  type JobFormValues,
} from '../lib/jobForm'
import { EDITABLE_STATUSES } from '../lib/lifecycle'

function Section({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="grid gap-5">{children}</CardContent>
    </Card>
  )
}

function FormSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-busy="true" aria-label="Loading job">
      <Skeleton className="h-9 w-64" />
      <Skeleton className="h-72 rounded-xl" />
      <Skeleton className="h-72 rounded-xl" />
    </div>
  )
}

type Mode = 'draft' | 'publish' | 'save'

function JobForm({ job }: { job?: JobDetail }) {
  const editing = Boolean(job)
  const { user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const create = useCreateJob()
  const update = useUpdateJob(job?.id ?? '')
  const transition = useJobTransition()
  const members = useCompanyMembers(job?.company_id ?? user?.company_id)
  const [formError, setFormError] = useState<string | null>(null)
  const [problems, setProblems] = useState<string[]>(
    (location.state as { publishProblems?: string[] } | null)?.publishProblems ?? [],
  )
  const [busy, setBusy] = useState<Mode | null>(null)
  const allowLeave = useRef(false)

  const schema = useMemo(
    () => buildJobSchema({ originalDeadline: job?.application_deadline }),
    [job?.application_deadline],
  )
  const defaults = useMemo(() => (job ? jobToFormValues(job) : EMPTY_JOB_FORM), [job])
  const form = useForm<JobFormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaults,
    mode: 'onTouched',
  })
  const {
    register,
    handleSubmit,
    setError,
    reset,
    control,
    formState: { errors, isDirty },
  } = form

  const description = useWatch({ control, name: 'description' })
  const status = job?.status ?? 'DRAFT'
  const isLive = editing && status !== 'DRAFT'

  // --- unsaved-changes guard (in-app navigation + tab close) -------------------------------------------------------------
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      isDirty && !allowLeave.current && currentLocation.pathname !== nextLocation.pathname,
  )
  useEffect(() => {
    if (!isDirty) return
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (allowLeave.current) return
      e.preventDefault()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [isDirty])

  const leaveTo = (to: string, state?: unknown) => {
    allowLeave.current = true
    navigate(to, { replace: true, state })
  }

  // --- submit --------------------------------------------------------------------------------------------------------------
  const run = (mode: Mode) =>
    handleSubmit(async (values) => {
      setFormError(null)
      setProblems([])
      if (mode === 'publish') {
        const missing = publishProblems(values)
        if (missing.length) {
          missing.forEach((p, i) =>
            setError(p.field, { type: 'publish', message: p.message }, { shouldFocus: i === 0 }),
          )
          setProblems(missing.map((p) => p.message))
          focusFirstError()
          return
        }
      }
      setBusy(mode)
      const payload = formValuesToPayload(values)
      let jobId = job?.id
      try {
        if (job) {
          await update.mutateAsync(payload)
        } else {
          const created = await create.mutateAsync({ body: payload })
          jobId = created.id
        }
      } catch (e) {
        setBusy(null)
        setFormError(
          applyApiErrors(e, setError, {
            fields: JOB_FORM_FIELDS,
            codeFields: JOB_ERROR_CODE_FIELDS,
            inferField: inferJobField,
          }),
        )
        focusFirstError()
        return
      }
      if (!jobId) return

      if (mode === 'publish' && status === 'DRAFT') {
        try {
          await transition.mutateAsync({ id: jobId, action: 'publish' })
        } catch (e) {
          // The content is saved; only the publish gate failed. Keep the user on the (now existing) draft with the reasons.
          setBusy(null)
          const d = describeLifecycleError(e)
          const list = d.problems?.length ? d.problems : [d.message]
          reset(values)
          toast.warning('Saved as a draft — but it can’t be published yet')
          if (!job) leaveTo(paths.manageJobEdit(jobId), { publishProblems: list })
          else {
            setFormError(null)
            setProblems(list)
          }
          return
        }
        toast.success('Job published', { description: values.title })
        reset(values)
        leaveTo(paths.job(jobId))
        return
      }

      setBusy(null)
      reset(values)
      if (!job) {
        toast.success('Draft saved')
        leaveTo(paths.manageJobEdit(jobId))
      } else {
        toast.success(isLive ? 'Changes saved' : 'Draft saved', {
          description:
            status === 'PUBLISHED' ? 'Candidate matches will refresh in the background.' : undefined,
        })
      }
    }, onInvalid)

  const onInvalid: SubmitErrorHandler<JobFormValues> = () => {
    setFormError('Some fields need your attention. They are highlighted below.')
    focusFirstError()
  }

  // --- options ---------------------------------------------------------------------------------------------------------------
  const managerOptions = (members.data ?? []).filter(
    (m) => m.status === 'ACTIVE' && (m.role === 'HIRING_MANAGER' || m.role === 'RECRUITER'),
  )
  const currentManager = job?.hiring_manager_id
  if (currentManager && !managerOptions.some((m) => m.id === currentManager)) {
    managerOptions.push({
      id: currentManager,
      email: '',
      first_name: job?.hiring_manager_name ?? 'Current hiring manager',
      last_name: '',
      role: 'HIRING_MANAGER',
      status: 'ACTIVE',
      is_company_admin: false,
    })
  }
  const currencies =
    job && !(CURRENCIES as readonly string[]).includes(job.salary_currency)
      ? [...CURRENCIES, job.salary_currency]
      : [...CURRENCIES]
  const today = dates.isoDate()
  const deadlineMin = !job?.application_deadline || job.application_deadline >= today ? today : undefined

  const title = editing ? `Edit “${job?.title}”` : 'Create a job'
  return (
    <>
      <PageHeader
        title={title}
        description={
          editing
            ? 'Update the posting. Fields marked * are required.'
            : 'Describe the role. You can save a draft and publish when it is ready.'
        }
        breadcrumbs={[
          { label: 'Jobs', to: paths.manageJobs },
          ...(job ? [{ label: job.title, to: paths.job(job.id) }] : []),
          { label: editing ? 'Edit' : 'New job' },
        ]}
        actions={
          job && (
            <Button asChild variant="outline">
              <Link to={paths.job(job.id)}>
                <Eye /> View job
              </Link>
            </Button>
          )
        }
        meta={
          job && (
            <span className="text-sm text-muted-foreground">Status: {JOB_STATUS_LABELS[job.status]}</span>
          )
        }
      />

      <form
        onSubmit={run(isLive ? 'save' : 'draft')}
        noValidate
        className="mx-auto grid max-w-4xl gap-6"
        aria-label={editing ? 'Edit job' : 'Create job'}
      >
        {formError && <Alert variant="danger">{formError}</Alert>}
        {problems.length > 0 && (
          <Alert variant="warning" title="This job can’t be published yet">
            <ul>
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </Alert>
        )}
        {status === 'PUBLISHED' && (
          <Alert variant="info" title="This job is live">
            Changes are visible to candidates as soon as you save, and candidate matches are refreshed in the
            background.
          </Alert>
        )}

        <Section title="Basics" description="What candidates see first.">
          <Field label="Job title" error={errors.title?.message} required>
            <Input placeholder="e.g. Senior Backend Engineer" autoComplete="off" {...register('title')} />
          </Field>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Department" error={errors.department?.message} optional>
              <Input placeholder="e.g. Platform" {...register('department')} />
            </Field>
            <Field
              label="Location"
              error={errors.location?.message}
              optional
              hint="City and country, or “Anywhere” for fully remote roles."
            >
              <Input placeholder="e.g. Berlin, Germany" {...register('location')} />
            </Field>
          </div>
          <div className="grid gap-5 sm:grid-cols-3">
            <Field label="Workplace" error={errors.workplace_type?.message} required>
              <NativeSelect {...register('workplace_type')}>
                {WORKPLACE_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Employment type" error={errors.employment_type?.message} required>
              <NativeSelect {...register('employment_type')}>
                {EMPLOYMENT_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Experience level" error={errors.experience_level?.message} optional>
              <NativeSelect {...register('experience_level')}>
                <option value="">Not specified</option>
                {EXPERIENCE_LEVEL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
        </Section>

        <Section title="Description" description="Be specific: this text also feeds candidate matching.">
          <Field
            label="About the role"
            error={errors.description?.message}
            required
            hint={`Publishing needs at least 30 characters. ${description.trim().length.toLocaleString()} so far.`}
          >
            <Textarea
              rows={7}
              placeholder="What will this person do, and why does the role exist?"
              {...register('description')}
            />
          </Field>
          <Field
            label="Responsibilities"
            error={errors.responsibilities?.message}
            optional
            hint="Start lines with “-” to make a bulleted list."
          >
            <Textarea rows={5} {...register('responsibilities')} />
          </Field>
          <Field label="Qualifications" error={errors.qualifications?.message} optional>
            <Textarea rows={4} {...register('qualifications')} />
          </Field>
          <Field label="Benefits" error={errors.benefits?.message} optional>
            <Textarea rows={3} {...register('benefits')} />
          </Field>
        </Section>

        <Section
          title="Requirements"
          description="Skills drive the match score candidates and recruiters see."
        >
          <div className="grid gap-5 sm:grid-cols-3">
            <Field label="Min. experience (years)" error={errors.min_experience_years?.message} required>
              <Input
                type="number"
                min={0}
                max={70}
                step={0.5}
                inputMode="decimal"
                {...register('min_experience_years')}
              />
            </Field>
            <Field label="Max. experience (years)" error={errors.max_experience_years?.message} optional>
              <Input
                type="number"
                min={0}
                max={70}
                step={0.5}
                inputMode="decimal"
                {...register('max_experience_years')}
              />
            </Field>
            <Field label="Minimum education" error={errors.min_education_level?.message} optional>
              <NativeSelect {...register('min_education_level')}>
                <option value="">Not specified</option>
                {EDUCATION_LEVEL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
          <Field
            label="Skills"
            htmlFor="job-skills"
            error={
              typeof errors.skills?.message === 'string'
                ? errors.skills.message
                : errors.skills?.root?.message
            }
            hint="Add at least one required skill to publish. Can't find a skill? Type its name and add it."
          >
            <SkillsEditor control={control} register={register} errors={errors} inputId="job-skills" />
          </Field>
        </Section>

        <Section title="Compensation" description="Shown to candidates. Leave blank to keep it private.">
          <div className="grid gap-5 sm:grid-cols-3">
            <Field label="Salary from (yearly)" error={errors.salary_min?.message} optional>
              <Input
                type="number"
                min={0}
                step={1000}
                inputMode="decimal"
                placeholder="e.g. 70000"
                {...register('salary_min')}
              />
            </Field>
            <Field label="Salary up to (yearly)" error={errors.salary_max?.message} optional>
              <Input
                type="number"
                min={0}
                step={1000}
                inputMode="decimal"
                placeholder="e.g. 95000"
                {...register('salary_max')}
              />
            </Field>
            <Field label="Currency" error={errors.salary_currency?.message} required>
              <NativeSelect {...register('salary_currency')}>
                {currencies.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
        </Section>

        <Section title="Hiring" description="Who owns the process and until when applications are accepted.">
          <div className="grid gap-5 sm:grid-cols-2">
            <Field
              label="Application deadline"
              error={errors.application_deadline?.message}
              optional
              hint="Leave empty to accept applications until the job is closed."
            >
              <Input type="date" min={deadlineMin} {...register('application_deadline')} />
            </Field>
            <Field
              label="Hiring manager"
              error={errors.hiring_manager_id?.message}
              optional
              hint={
                members.isError
                  ? 'Could not load your team. You can assign a manager later.'
                  : 'They see this job and its applicants.'
              }
            >
              <NativeSelect disabled={members.isPending} {...register('hiring_manager_id')}>
                <option value="">{members.isPending ? 'Loading team…' : 'Unassigned'}</option>
                {managerOptions.map((m) => (
                  <option key={m.id} value={m.id}>
                    {`${m.first_name} ${m.last_name}`.trim()} — {ROLE_LABELS[m.role]}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
        </Section>

        <div className="sticky bottom-0 z-20 -mx-4 flex flex-wrap items-center justify-end gap-2 border-t bg-background/90 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          {isDirty && <span className="mr-auto text-sm text-muted-foreground">Unsaved changes</span>}
          <Button
            type="button"
            variant="ghost"
            onClick={() => navigate(job ? paths.job(job.id) : paths.manageJobs)}
            disabled={busy !== null}
          >
            Cancel
          </Button>
          {isLive ? (
            <Button type="submit" loading={busy === 'save'} disabled={busy !== null && busy !== 'save'}>
              <Save /> Save changes
            </Button>
          ) : (
            <>
              <Button
                type="submit"
                variant="outline"
                loading={busy === 'draft'}
                disabled={busy !== null && busy !== 'draft'}
              >
                <Save /> Save as draft
              </Button>
              <Button
                type="button"
                onClick={run('publish')}
                loading={busy === 'publish'}
                disabled={busy !== null && busy !== 'publish'}
              >
                <Rocket /> Publish
              </Button>
            </>
          )}
        </div>
      </form>

      <ConfirmDialog
        open={blocker.state === 'blocked'}
        onOpenChange={(o) => {
          if (!o && blocker.state === 'blocked') blocker.reset()
        }}
        title="Leave without saving?"
        description="You have unsaved changes to this job. If you leave now they will be lost."
        confirmLabel="Discard changes"
        cancelLabel="Keep editing"
        destructive
        onConfirm={() => blocker.state === 'blocked' && blocker.proceed()}
      />
    </>
  )
}

export default function JobFormPage() {
  const { id } = useParams()
  const job = useJob(id)
  useDocumentTitle(id ? 'Edit job' : 'New job')

  if (!id) return <JobForm />
  if (job.isPending) return <FormSkeleton />
  if (job.isError) {
    return (
      <ErrorState
        error={job.error}
        onRetry={() => job.refetch()}
        title={job.error instanceof ApiError && job.error.status === 404 ? 'Job not found' : undefined}
      />
    )
  }
  if (!isStaffView(job.data)) {
    return <ErrorState error={new ApiError(403, 'FORBIDDEN', 'Only the owning company can edit this job.')} />
  }
  if (!EDITABLE_STATUSES.includes(job.data.status)) {
    return (
      <div className="mx-auto max-w-xl py-10">
        <Alert variant="info" title={`${JOB_STATUS_LABELS[job.data.status]} jobs can't be edited`}>
          Closed and archived jobs are read-only. <Link to={paths.job(job.data.id)}>Back to the job</Link>.
        </Alert>
      </div>
    )
  }
  return <JobForm key={job.data.id} job={job.data} />
}
