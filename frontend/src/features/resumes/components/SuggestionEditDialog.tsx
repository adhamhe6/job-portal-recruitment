import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { Checkbox } from '@/components/ui/checkbox'
import { Field } from '@/components/ui/field'
import { Input, NativeSelect, Textarea } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { EntryDialog } from '@/features/profile/components/Section'
import { LANGUAGE_LEVEL_OPTIONS } from '@/features/profile/lib/forms'
import { EDUCATION_LEVEL_OPTIONS } from '@/lib/enums'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import type { EducationLevel } from '@/lib/api'
import type {
  ExtractedCertification,
  ExtractedEducation,
  ExtractedExperience,
  ExtractedLanguage,
  ExtractedPatch,
  ExtractedSkill,
} from '../api/resumes'
import type { ListSection } from '../lib/review'

/**
 * Correct one suggestion (PATCH /resumes/{id}/extracted). Only the stored suggestion changes — never the profile — and
 * the dialog validates like the profile forms do. Required text fields cannot be cleared (the API rejects empty values).
 */

export type EditTarget =
  | { section: 'skills'; item: ExtractedSkill }
  | { section: 'experiences'; item: ExtractedExperience }
  | { section: 'educations'; item: ExtractedEducation }
  | { section: 'certifications'; item: ExtractedCertification }
  | { section: 'languages'; item: ExtractedLanguage }

const nonEmpty = (label: string, max: number) =>
  z.string().trim().min(1, `${label} is required`).max(max, `${label} is too long`)
const optional = (max: number) => z.string().trim().max(max, `Must be at most ${max} characters`)
const date = z.string().refine((v) => v === '' || /^\d{4}-\d{2}-\d{2}$/.test(v), 'Enter a valid date')
const year = z
  .string()
  .trim()
  .refine(
    (v) => v === '' || (/^\d{4}$/.test(v) && Number(v) >= 1950 && Number(v) <= 2100),
    'Enter a year between 1950 and 2100',
  )
const orNull = (v: string) => (v.trim() === '' ? null : v.trim())

type Save = (patch: ExtractedPatch) => Promise<void>

interface DialogProps<T> {
  item: T
  onClose: () => void
  save: Save
}

function useSubmit<V extends Record<string, unknown>>(
  form: ReturnType<typeof useForm<V>>,
  fields: string[],
  build: (values: V) => ExtractedPatch,
  save: Save,
  onClose: () => void,
) {
  const [pending, setPending] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const submit = form.handleSubmit(
    async (values) => {
      setFormError(null)
      setPending(true)
      try {
        await save(build(values))
        onClose()
      } catch (e) {
        setFormError(applyApiErrors(e, form.setError, { fields }))
        focusFirstError()
      } finally {
        setPending(false)
      }
    },
    () => focusFirstError(),
  )
  return { submit, pending, formError }
}

// --- skill -----------------------------------------------------------------------------------------------------------

const skillSchema = z.object({ name: nonEmpty('Skill name', 100) })
type SkillV = z.infer<typeof skillSchema>

function SkillEdit({ item, onClose, save }: DialogProps<ExtractedSkill>) {
  const form = useForm<SkillV>({
    resolver: zodResolver(skillSchema),
    defaultValues: { name: item.name },
    mode: 'onTouched',
  })
  const { submit, pending, formError } = useSubmit(
    form,
    ['name'],
    (v) => ({ skills: [{ index: item.index, name: v.name }] }),
    save,
    onClose,
  )
  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Edit skill suggestion"
      description="The name is matched against the skill library again after you save."
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label="Skill name" required error={form.formState.errors.name?.message}>
        <Input {...form.register('name')} />
      </Field>
    </EntryDialog>
  )
}

// --- experience ------------------------------------------------------------------------------------------------------

const experienceSchema = z
  .object({
    title: optional(200),
    company: optional(200),
    location: optional(200),
    start_date: date,
    end_date: date,
    is_current: z.boolean(),
    description: optional(5000),
  })
  .superRefine((v, ctx) => {
    if (!v.is_current && v.start_date && v.end_date && v.end_date < v.start_date)
      ctx.addIssue({
        code: 'custom',
        path: ['end_date'],
        message: 'End date must not be before the start date',
      })
  })
type ExperienceV = z.infer<typeof experienceSchema>

function ExperienceEdit({ item, onClose, save }: DialogProps<ExtractedExperience>) {
  const form = useForm<ExperienceV>({
    resolver: zodResolver(experienceSchema),
    defaultValues: {
      title: item.title ?? '',
      company: item.company ?? '',
      location: item.location ?? '',
      start_date: item.start_date ?? '',
      end_date: item.end_date ?? '',
      is_current: item.is_current,
      description: item.description ?? '',
    },
    mode: 'onTouched',
  })
  const current = useWatch({ control: form.control, name: 'is_current' })
  const { submit, pending, formError } = useSubmit(
    form,
    ['title', 'company', 'location', 'start_date', 'end_date', 'description'],
    (v) => ({
      experiences: [
        {
          index: item.index,
          ...(v.title ? { title: v.title } : {}),
          ...(v.company ? { company: v.company } : {}),
          location: orNull(v.location),
          start_date: orNull(v.start_date),
          end_date: v.is_current ? null : orNull(v.end_date),
          is_current: v.is_current,
          description: orNull(v.description),
        },
      ],
    }),
    save,
    onClose,
  )
  const { errors } = form.formState
  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Edit experience suggestion"
      description="Job title, company and start date are needed before it can be added to your profile."
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label="Job title" error={errors.title?.message}>
        <Input {...form.register('title')} />
      </Field>
      <Field label="Company" error={errors.company?.message}>
        <Input {...form.register('company')} />
      </Field>
      <Field label="Location" optional error={errors.location?.message}>
        <Input {...form.register('location')} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Start date" error={errors.start_date?.message}>
          <Input type="date" {...form.register('start_date')} />
        </Field>
        <Field label="End date" optional error={errors.end_date?.message}>
          <Input type="date" disabled={current} {...form.register('end_date')} />
        </Field>
      </div>
      <div className="flex items-center gap-2">
        <Controller
          control={form.control}
          name="is_current"
          render={({ field }) => (
            <Checkbox
              id="sx-current"
              checked={field.value}
              onCheckedChange={(c) => field.onChange(c === true)}
            />
          )}
        />
        <Label htmlFor="sx-current">I currently work here</Label>
      </div>
      <Field label="Description" optional error={errors.description?.message}>
        <Textarea rows={4} {...form.register('description')} />
      </Field>
    </EntryDialog>
  )
}

// --- education -------------------------------------------------------------------------------------------------------

const educationSchema = z
  .object({
    institution: optional(200),
    degree_level: z.string(),
    degree: optional(200),
    field_of_study: optional(200),
    start_year: year,
    end_year: year,
  })
  .superRefine((v, ctx) => {
    if (v.start_year && v.end_year && Number(v.end_year) < Number(v.start_year))
      ctx.addIssue({
        code: 'custom',
        path: ['end_year'],
        message: 'End year must not be before the start year',
      })
  })
type EducationV = z.infer<typeof educationSchema>

function EducationEdit({ item, onClose, save }: DialogProps<ExtractedEducation>) {
  const form = useForm<EducationV>({
    resolver: zodResolver(educationSchema),
    defaultValues: {
      institution: item.institution ?? '',
      degree_level: item.degree_level ?? '',
      degree: item.degree ?? '',
      field_of_study: item.field_of_study ?? '',
      start_year: item.start_year ? String(item.start_year) : '',
      end_year: item.end_year ? String(item.end_year) : '',
    },
    mode: 'onTouched',
  })
  const { submit, pending, formError } = useSubmit(
    form,
    ['institution', 'degree', 'degree_level', 'field_of_study', 'start_year', 'end_year'],
    (v) => ({
      educations: [
        {
          index: item.index,
          ...(v.institution ? { institution: v.institution } : {}),
          degree_level: (v.degree_level || null) as EducationLevel | null,
          degree: orNull(v.degree),
          field_of_study: orNull(v.field_of_study),
          start_year: v.start_year ? Number(v.start_year) : null,
          end_year: v.end_year ? Number(v.end_year) : null,
        },
      ],
    }),
    save,
    onClose,
  )
  const { errors } = form.formState
  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Edit education suggestion"
      description="Institution and level are needed before it can be added to your profile."
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label="Institution" error={errors.institution?.message}>
        <Input {...form.register('institution')} />
      </Field>
      <Field label="Level" error={errors.degree_level?.message}>
        <NativeSelect {...form.register('degree_level')}>
          <option value="">Not specified</option>
          {EDUCATION_LEVEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Degree" optional error={errors.degree?.message}>
          <Input {...form.register('degree')} />
        </Field>
        <Field label="Field of study" optional error={errors.field_of_study?.message}>
          <Input {...form.register('field_of_study')} />
        </Field>
        <Field label="Start year" optional error={errors.start_year?.message}>
          <Input inputMode="numeric" {...form.register('start_year')} />
        </Field>
        <Field label="End year" optional error={errors.end_year?.message}>
          <Input inputMode="numeric" {...form.register('end_year')} />
        </Field>
      </div>
    </EntryDialog>
  )
}

// --- certification ---------------------------------------------------------------------------------------------------

const certificationSchema = z.object({ name: nonEmpty('Name', 200), issuer: optional(200), issued_on: date })
type CertificationV = z.infer<typeof certificationSchema>

function CertificationEdit({ item, onClose, save }: DialogProps<ExtractedCertification>) {
  const form = useForm<CertificationV>({
    resolver: zodResolver(certificationSchema),
    defaultValues: { name: item.name, issuer: item.issuer ?? '', issued_on: item.issued_on ?? '' },
    mode: 'onTouched',
  })
  const { submit, pending, formError } = useSubmit(
    form,
    ['name', 'issuer', 'issued_on'],
    (v) => ({
      certifications: [
        { index: item.index, name: v.name, issuer: orNull(v.issuer), issued_on: orNull(v.issued_on) },
      ],
    }),
    save,
    onClose,
  )
  const { errors } = form.formState
  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Edit certification suggestion"
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label="Name" required error={errors.name?.message}>
        <Input {...form.register('name')} />
      </Field>
      <Field label="Issuing organisation" optional error={errors.issuer?.message}>
        <Input {...form.register('issuer')} />
      </Field>
      <Field label="Issued on" optional error={errors.issued_on?.message}>
        <Input type="date" {...form.register('issued_on')} />
      </Field>
    </EntryDialog>
  )
}

// --- language --------------------------------------------------------------------------------------------------------

const languageSchema = z.object({
  language: z
    .string()
    .trim()
    .min(2, 'Language must be at least 2 characters')
    .max(60, 'Language is too long'),
  proficiency: z.string(),
})
type LanguageV = z.infer<typeof languageSchema>

function LanguageEdit({ item, onClose, save }: DialogProps<ExtractedLanguage>) {
  const form = useForm<LanguageV>({
    resolver: zodResolver(languageSchema),
    defaultValues: { language: item.language, proficiency: item.proficiency ?? '' },
    mode: 'onTouched',
  })
  const { submit, pending, formError } = useSubmit(
    form,
    ['language', 'proficiency'],
    (v) => ({
      languages: [
        {
          index: item.index,
          language: v.language,
          proficiency: (v.proficiency || null) as ExtractedLanguage['proficiency'],
        },
      ],
    }),
    save,
    onClose,
  )
  const { errors } = form.formState
  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Edit language suggestion"
      description="A proficiency level is needed before it can be added to your profile."
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label="Language" required error={errors.language?.message}>
        <Input {...form.register('language')} />
      </Field>
      <Field label="Proficiency" error={errors.proficiency?.message}>
        <NativeSelect {...form.register('proficiency')}>
          <option value="">Not specified</option>
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

export function SuggestionEditDialog({
  target,
  onClose,
  save,
}: {
  target: EditTarget
  onClose: () => void
  save: Save
}) {
  const key = `${target.section}-${target.item.index}`
  switch (target.section) {
    case 'skills':
      return <SkillEdit key={key} item={target.item} onClose={onClose} save={save} />
    case 'experiences':
      return <ExperienceEdit key={key} item={target.item} onClose={onClose} save={save} />
    case 'educations':
      return <EducationEdit key={key} item={target.item} onClose={onClose} save={save} />
    case 'certifications':
      return <CertificationEdit key={key} item={target.item} onClose={onClose} save={save} />
    case 'languages':
      return <LanguageEdit key={key} item={target.item} onClose={onClose} save={save} />
  }
}

export type { ListSection }
