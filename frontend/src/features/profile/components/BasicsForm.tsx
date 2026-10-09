import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input, NativeSelect, Textarea } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { CURRENCIES } from '@/lib/enums'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { useUpdateProfile } from '../api/profile'
import {
  AVAILABILITY_OPTIONS,
  basicsDefaults,
  BASICS_FIELDS,
  basicsPayload,
  basicsSchema,
  EMPLOYMENT_PREFERENCE_OPTIONS,
  REMOTE_OPTIONS,
  type BasicsValues,
} from '../lib/forms'
import type { CandidateProfile } from '../lib/types'
import { SectionCard } from './Section'

export function BasicsForm({ profile }: { profile: CandidateProfile }) {
  const update = useUpdateProfile()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<BasicsValues>({
    resolver: zodResolver(basicsSchema),
    defaultValues: basicsDefaults(profile),
    mode: 'onTouched',
  })
  const { register, handleSubmit, setError, control, reset, formState } = form
  const { errors, isDirty } = formState
  const summary = useWatch({ control, name: 'summary' })

  const submit = handleSubmit(
    async (values) => {
      setFormError(null)
      try {
        const saved = await update.mutateAsync(basicsPayload(values))
        reset(basicsDefaults(saved))
        toast.success('Profile saved')
      } catch (e) {
        setFormError(applyApiErrors(e, setError, { fields: BASICS_FIELDS }))
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  const currencies = CURRENCIES.includes(profile.salary_currency as (typeof CURRENCIES)[number])
    ? CURRENCIES
    : [profile.salary_currency, ...CURRENCIES]

  return (
    <SectionCard id="basics" title="About you" description="What recruiters see first.">
      <form onSubmit={submit} noValidate className="grid gap-5" aria-label="Profile details">
        {formError && <Alert variant="danger">{formError}</Alert>}
        <Field
          label="Headline"
          hint="e.g. Senior backend engineer · Python & PostgreSQL"
          error={errors.headline?.message}
        >
          <Input {...register('headline')} maxLength={200} />
        </Field>
        <Field label="Professional summary" error={errors.summary?.message}>
          <Textarea rows={5} maxLength={5000} {...register('summary')} />
        </Field>
        <p className="-mt-3 text-right text-xs text-muted-foreground tabular">
          {summary.length.toLocaleString()} / 5,000
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Location" error={errors.location?.message}>
            <Input autoComplete="address-level2" placeholder="City, Country" {...register('location')} />
          </Field>
          <Field label="Phone" error={errors.phone?.message}>
            <Input type="tel" autoComplete="tel" {...register('phone')} />
          </Field>
          <Field label="Years of experience" error={errors.years_experience?.message}>
            <Input inputMode="decimal" {...register('years_experience')} />
          </Field>
          <Field label="Availability" error={errors.availability?.message}>
            <NativeSelect {...register('availability')}>
              <option value="">Not specified</option>
              {AVAILABILITY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </NativeSelect>
          </Field>
        </div>

        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-2 text-sm font-semibold">Work preferences</legend>
          <Field label="Workplace" error={errors.remote_preference?.message}>
            <NativeSelect {...register('remote_preference')}>
              <option value="">No preference</option>
              {REMOTE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Employment type" error={errors.employment_preference?.message}>
            <NativeSelect {...register('employment_preference')}>
              <option value="">No preference</option>
              {EMPLOYMENT_PREFERENCE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Expected salary (yearly)" error={errors.expected_salary?.message}>
            <Input inputMode="decimal" {...register('expected_salary')} />
          </Field>
          <Field label="Currency" error={errors.salary_currency?.message}>
            <NativeSelect {...register('salary_currency')}>
              {currencies.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </NativeSelect>
          </Field>
        </fieldset>

        <fieldset className="grid gap-4 sm:grid-cols-3">
          <legend className="mb-2 text-sm font-semibold">Links</legend>
          <Field label="LinkedIn" error={errors.linkedin_url?.message}>
            <Input inputMode="url" placeholder="https://linkedin.com/in/…" {...register('linkedin_url')} />
          </Field>
          <Field label="GitHub" error={errors.github_url?.message}>
            <Input inputMode="url" placeholder="https://github.com/…" {...register('github_url')} />
          </Field>
          <Field label="Portfolio" error={errors.portfolio_url?.message}>
            <Input inputMode="url" placeholder="https://" {...register('portfolio_url')} />
          </Field>
        </fieldset>

        <div className="flex items-start justify-between gap-4 rounded-lg border bg-surface p-3">
          <div className="space-y-0.5">
            <label htmlFor="is-searchable" className="text-sm font-medium">
              Visible to recruiters
            </label>
            <p id="is-searchable-hint" className="text-xs text-muted-foreground">
              When on, recruiters can find your profile in candidate search. Companies you apply to always see
              your application.
            </p>
          </div>
          <Controller
            control={control}
            name="is_searchable"
            render={({ field }) => (
              <Switch
                id="is-searchable"
                aria-describedby="is-searchable-hint"
                checked={field.value}
                onCheckedChange={field.onChange}
              />
            )}
          />
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          {isDirty && <span className="text-xs text-muted-foreground">You have unsaved changes</span>}
          <Button
            type="button"
            variant="outline"
            disabled={!isDirty || update.isPending}
            onClick={() => reset()}
          >
            Discard
          </Button>
          <Button type="submit" loading={update.isPending} disabled={!isDirty}>
            Save changes
          </Button>
        </div>
      </form>
    </SectionCard>
  )
}
