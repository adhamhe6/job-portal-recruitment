import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { EmptyState } from '@/components/common/States'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Field } from '@/components/ui/field'
import { Input, NativeSelect, Textarea } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { EDUCATION_LEVEL_LABELS, EDUCATION_LEVEL_OPTIONS } from '@/lib/enums'
import { errorMessage } from '@/lib/api'
import { dates } from '@/lib/format'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import {
  useCertificationMutations,
  useEducationMutations,
  useExperienceMutations,
  useLanguageMutations,
} from '../api/profile'
import {
  certificationDefaults,
  certificationPayload,
  certificationSchema,
  educationDefaults,
  educationPayload,
  educationSchema,
  experienceDefaults,
  experiencePayload,
  experienceSchema,
  LANGUAGE_LEVEL_OPTIONS,
  languagePayload,
  languageSchema,
  labelOf,
  type CertificationValues,
  type EducationValues,
  type ExperienceValues,
  type LanguageValues,
} from '../lib/forms'
import type { Certification, Education, Experience, Language } from '../lib/types'
import { EntryDialog, EntryRow, SectionCard } from './Section'

type Editing<T> = { item: T | null } | null

function monthYear(d: string | null | undefined) {
  return d ? dates.date(d).replace(/ \d{1,2},/, '') : ''
}

function useDeleteFlow<T extends { id: string }>(remove: (id: string) => Promise<unknown>, noun: string) {
  const [target, setTarget] = useState<T | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const confirm = async () => {
    if (!target) return
    setPending(true)
    setError(null)
    try {
      await remove(target.id)
      setTarget(null)
      toast.success(`${noun} removed`)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setPending(false)
    }
  }
  const request = (t: T) => {
    setError(null)
    setTarget(t)
  }
  return { target, request, close: () => setTarget(null), confirm, pending, error }
}

interface DeleteFlow {
  target: unknown
  close: () => void
  confirm: () => void | Promise<void>
  pending: boolean
  error: string | null
}

function DeleteConfirm({
  flow,
  title,
  description,
}: {
  flow: DeleteFlow
  title: string
  description: string
}) {
  return (
    <ConfirmDialog
      open={flow.target !== null}
      onOpenChange={(o) => !o && flow.close()}
      title={title}
      description={description}
      confirmLabel="Delete"
      destructive
      loading={flow.pending}
      onConfirm={flow.confirm}
    >
      {flow.error && (
        <p role="alert" className="text-sm text-destructive">
          {flow.error}
        </p>
      )}
    </ConfirmDialog>
  )
}

const FromResume = ({ source }: { source: string }) =>
  source === 'RESUME' ? <Badge variant="info">From résumé</Badge> : null

// --- experience ------------------------------------------------------------------------------------------------------

function ExperienceDialog({ item, onClose }: { item: Experience | null; onClose: () => void }) {
  const { create, update } = useExperienceMutations()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<ExperienceValues>({
    resolver: zodResolver(experienceSchema),
    defaultValues: experienceDefaults(item ?? undefined),
    mode: 'onTouched',
  })
  const { register, handleSubmit, setError, control, formState } = form
  const { errors } = formState
  const current = useWatch({ control, name: 'is_current' })
  const pending = create.isPending || update.isPending

  const submit = handleSubmit(
    async (values) => {
      setFormError(null)
      try {
        const body = experiencePayload(values)
        if (item) await update.mutateAsync({ id: item.id, body })
        else await create.mutateAsync(body)
        toast.success(item ? 'Experience updated' : 'Experience added')
        onClose()
      } catch (e) {
        setFormError(
          applyApiErrors(e, setError, {
            fields: Object.keys(experienceSchema.innerType().shape),
            inferField: (m) =>
              m.includes('start_date') ? 'start_date' : m.includes('end_date') ? 'end_date' : undefined,
          }),
        )
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={item ? 'Edit experience' : 'Add experience'}
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label="Job title" required error={errors.title?.message}>
        <Input autoComplete="organization-title" {...register('title')} />
      </Field>
      <Field label="Company" required error={errors.company_name?.message}>
        <Input autoComplete="organization" {...register('company_name')} />
      </Field>
      <Field label="Location" optional error={errors.location?.message}>
        <Input {...register('location')} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Start date" required error={errors.start_date?.message}>
          <Input type="date" max={dates.isoDate()} {...register('start_date')} />
        </Field>
        <Field label="End date" optional error={errors.end_date?.message}>
          <Input type="date" disabled={current} {...register('end_date')} />
        </Field>
      </div>
      <div className="flex items-center gap-2">
        <Controller
          control={control}
          name="is_current"
          render={({ field }) => (
            <Checkbox
              id="exp-current"
              checked={field.value}
              onCheckedChange={(c) => field.onChange(c === true)}
            />
          )}
        />
        <Label htmlFor="exp-current">I currently work here</Label>
      </div>
      <Field label="Description" optional error={errors.description?.message}>
        <Textarea rows={4} {...register('description')} />
      </Field>
    </EntryDialog>
  )
}

export function ExperienceSection({ items }: { items: Experience[] }) {
  const [editing, setEditing] = useState<Editing<Experience>>(null)
  const { remove } = useExperienceMutations()
  const del = useDeleteFlow<Experience>((id) => remove.mutateAsync(id), 'Experience')
  const sorted = [...items].sort((a, b) => b.start_date.localeCompare(a.start_date))
  return (
    <SectionCard
      id="experience"
      title="Work experience"
      description="Roles you have held, newest first."
      addLabel="Add experience"
      onAdd={() => setEditing({ item: null })}
    >
      {sorted.length === 0 ? (
        <EmptyState
          compact
          title="No work experience yet"
          description="Add your roles so recruiters and the matching engine can see your background."
        />
      ) : (
        <ul className="divide-y" aria-label="Work experience">
          {sorted.map((e) => (
            <EntryRow
              key={e.id}
              label={`${e.title} at ${e.company_name}`}
              title={e.title}
              badge={<FromResume source={e.source} />}
              subtitle={`${e.company_name}${e.location ? ` · ${e.location}` : ''}`}
              meta={`${monthYear(e.start_date)} – ${e.is_current ? 'Present' : monthYear(e.end_date) || '—'}`}
              onEdit={() => setEditing({ item: e })}
              onDelete={() => del.request(e)}
            >
              {e.description && (
                <p className="line-clamp-3 pt-1 text-sm whitespace-pre-line text-muted-foreground">
                  {e.description}
                </p>
              )}
            </EntryRow>
          ))}
        </ul>
      )}
      {editing && (
        <ExperienceDialog
          key={editing.item?.id ?? 'new'}
          item={editing.item}
          onClose={() => setEditing(null)}
        />
      )}
      <DeleteConfirm
        flow={del}
        title="Delete this experience?"
        description={`“${del.target?.title ?? ''}” at ${del.target?.company_name ?? ''} will be removed from your profile.`}
      />
    </SectionCard>
  )
}

// --- education -------------------------------------------------------------------------------------------------------

function EducationDialog({ item, onClose }: { item: Education | null; onClose: () => void }) {
  const { create, update } = useEducationMutations()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<EducationValues>({
    resolver: zodResolver(educationSchema),
    defaultValues: educationDefaults(item ?? undefined),
    mode: 'onTouched',
  })
  const { register, handleSubmit, setError, formState } = form
  const { errors } = formState
  const pending = create.isPending || update.isPending

  const submit = handleSubmit(
    async (values) => {
      setFormError(null)
      try {
        const body = educationPayload(values)
        if (item) await update.mutateAsync({ id: item.id, body })
        else await create.mutateAsync(body)
        toast.success(item ? 'Education updated' : 'Education added')
        onClose()
      } catch (e) {
        setFormError(applyApiErrors(e, setError, { fields: Object.keys(educationSchema.innerType().shape) }))
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={item ? 'Edit education' : 'Add education'}
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label="Institution" required error={errors.institution?.message}>
        <Input {...register('institution')} />
      </Field>
      <Field label="Level" required error={errors.degree_level?.message}>
        <NativeSelect {...register('degree_level')}>
          <option value="">Select a level…</option>
          {EDUCATION_LEVEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Degree" optional error={errors.degree?.message}>
          <Input placeholder="e.g. B.Sc." {...register('degree')} />
        </Field>
        <Field label="Field of study" optional error={errors.field_of_study?.message}>
          <Input {...register('field_of_study')} />
        </Field>
        <Field label="Start year" optional error={errors.start_year?.message}>
          <Input inputMode="numeric" placeholder="2016" {...register('start_year')} />
        </Field>
        <Field label="End year" optional error={errors.end_year?.message}>
          <Input inputMode="numeric" placeholder="2020" {...register('end_year')} />
        </Field>
      </div>
    </EntryDialog>
  )
}

export function EducationSection({ items }: { items: Education[] }) {
  const [editing, setEditing] = useState<Editing<Education>>(null)
  const { remove } = useEducationMutations()
  const del = useDeleteFlow<Education>((id) => remove.mutateAsync(id), 'Education')
  const sorted = [...items].sort((a, b) => (b.end_year ?? 9999) - (a.end_year ?? 9999))
  return (
    <SectionCard
      id="education"
      title="Education"
      description="Degrees and schools."
      addLabel="Add education"
      onAdd={() => setEditing({ item: null })}
    >
      {sorted.length === 0 ? (
        <EmptyState compact title="No education yet" description="Add your highest qualification to start." />
      ) : (
        <ul className="divide-y" aria-label="Education">
          {sorted.map((e) => (
            <EntryRow
              key={e.id}
              label={e.institution}
              title={e.institution}
              badge={<FromResume source={e.source} />}
              subtitle={
                [e.degree, e.field_of_study].filter(Boolean).join(' · ') ||
                EDUCATION_LEVEL_LABELS[e.degree_level]
              }
              meta={[
                EDUCATION_LEVEL_LABELS[e.degree_level],
                e.start_year || e.end_year ? `${e.start_year ?? ''} – ${e.end_year ?? ''}` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
              onEdit={() => setEditing({ item: e })}
              onDelete={() => del.request(e)}
            />
          ))}
        </ul>
      )}
      {editing && (
        <EducationDialog
          key={editing.item?.id ?? 'new'}
          item={editing.item}
          onClose={() => setEditing(null)}
        />
      )}
      <DeleteConfirm
        flow={del}
        title="Delete this education entry?"
        description={`${del.target?.institution ?? ''} will be removed from your profile.`}
      />
    </SectionCard>
  )
}

// --- certifications --------------------------------------------------------------------------------------------------

function CertificationDialog({ item, onClose }: { item: Certification | null; onClose: () => void }) {
  const { create, update } = useCertificationMutations()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<CertificationValues>({
    resolver: zodResolver(certificationSchema),
    defaultValues: certificationDefaults(item ?? undefined),
    mode: 'onTouched',
  })
  const { register, handleSubmit, setError, formState } = form
  const { errors } = formState
  const pending = create.isPending || update.isPending

  const submit = handleSubmit(
    async (values) => {
      setFormError(null)
      try {
        const body = certificationPayload(values)
        if (item) await update.mutateAsync({ id: item.id, body })
        else await create.mutateAsync(body)
        toast.success(item ? 'Certification updated' : 'Certification added')
        onClose()
      } catch (e) {
        setFormError(
          applyApiErrors(e, setError, { fields: Object.keys(certificationSchema.innerType().shape) }),
        )
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={item ? 'Edit certification' : 'Add certification'}
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label="Name" required error={errors.name?.message}>
        <Input {...register('name')} />
      </Field>
      <Field label="Issuing organisation" optional error={errors.issuer?.message}>
        <Input {...register('issuer')} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Issued on" optional error={errors.issued_on?.message}>
          <Input type="date" max={dates.isoDate()} {...register('issued_on')} />
        </Field>
        <Field label="Expires on" optional error={errors.expires_on?.message}>
          <Input type="date" {...register('expires_on')} />
        </Field>
      </div>
      <Field label="Credential URL" optional error={errors.credential_url?.message}>
        <Input type="url" inputMode="url" placeholder="https://" {...register('credential_url')} />
      </Field>
    </EntryDialog>
  )
}

export function CertificationSection({ items }: { items: Certification[] }) {
  const [editing, setEditing] = useState<Editing<Certification>>(null)
  const { remove } = useCertificationMutations()
  const del = useDeleteFlow<Certification>((id) => remove.mutateAsync(id), 'Certification')
  return (
    <SectionCard
      id="certifications"
      title="Certifications"
      description="Licences and professional credentials."
      addLabel="Add certification"
      onAdd={() => setEditing({ item: null })}
    >
      {items.length === 0 ? (
        <EmptyState
          compact
          title="No certifications yet"
          description="Optional, but they help you stand out."
        />
      ) : (
        <ul className="divide-y" aria-label="Certifications">
          {items.map((c) => (
            <EntryRow
              key={c.id}
              label={c.name}
              title={c.name}
              badge={<FromResume source={c.source} />}
              subtitle={c.issuer}
              meta={[
                c.issued_on ? `Issued ${dates.date(c.issued_on)}` : '',
                c.expires_on ? `Expires ${dates.date(c.expires_on)}` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
              onEdit={() => setEditing({ item: c })}
              onDelete={() => del.request(c)}
            />
          ))}
        </ul>
      )}
      {editing && (
        <CertificationDialog
          key={editing.item?.id ?? 'new'}
          item={editing.item}
          onClose={() => setEditing(null)}
        />
      )}
      <DeleteConfirm
        flow={del}
        title="Delete this certification?"
        description={`“${del.target?.name ?? ''}” will be removed from your profile.`}
      />
    </SectionCard>
  )
}

// --- languages -------------------------------------------------------------------------------------------------------

function LanguageDialog({ item, onClose }: { item: Language | null; onClose: () => void }) {
  const { create, remove } = useLanguageMutations()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<LanguageValues>({
    resolver: zodResolver(languageSchema),
    defaultValues: { language: item?.language ?? '', proficiency: item?.proficiency ?? '' },
    mode: 'onTouched',
  })
  const { register, handleSubmit, setError, formState } = form
  const { errors } = formState
  const pending = create.isPending || remove.isPending

  const submit = handleSubmit(
    async (values) => {
      setFormError(null)
      try {
        // The API has no PUT for languages: add the new row first, then drop the old one (never lose data on failure).
        await create.mutateAsync(languagePayload(values))
        if (item) await remove.mutateAsync(item.id)
        toast.success(item ? 'Language updated' : 'Language added')
        onClose()
      } catch (e) {
        setFormError(applyApiErrors(e, setError, { fields: ['language', 'proficiency'] }))
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={item ? 'Edit language' : 'Add language'}
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label="Language" required error={errors.language?.message}>
        <Input placeholder="e.g. German" {...register('language')} />
      </Field>
      <Field label="Proficiency" required error={errors.proficiency?.message}>
        <NativeSelect {...register('proficiency')}>
          <option value="">Select a level…</option>
          {LANGUAGE_LEVEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
    </EntryDialog>
  )
}

export function LanguageSection({ items }: { items: Language[] }) {
  const [editing, setEditing] = useState<Editing<Language>>(null)
  const { remove } = useLanguageMutations()
  const del = useDeleteFlow<Language>((id) => remove.mutateAsync(id), 'Language')
  return (
    <SectionCard
      id="languages"
      title="Languages"
      addLabel="Add language"
      onAdd={() => setEditing({ item: null })}
    >
      {items.length === 0 ? (
        <EmptyState compact title="No languages yet" description="List the languages you can work in." />
      ) : (
        <ul className="divide-y" aria-label="Languages">
          {items.map((l) => (
            <EntryRow
              key={l.id}
              label={l.language}
              title={l.language}
              meta={labelOf(LANGUAGE_LEVEL_OPTIONS, l.proficiency)}
              onEdit={() => setEditing({ item: l })}
              onDelete={() => del.request(l)}
            />
          ))}
        </ul>
      )}
      {editing && (
        <LanguageDialog
          key={editing.item?.id ?? 'new'}
          item={editing.item}
          onClose={() => setEditing(null)}
        />
      )}
      <DeleteConfirm
        flow={del}
        title="Remove this language?"
        description={`${del.target?.language ?? ''} will be removed from your profile.`}
      />
    </SectionCard>
  )
}
