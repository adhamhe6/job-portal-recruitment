import { zodResolver } from '@hookform/resolvers/zod'
import { Lock } from 'lucide-react'
import { useState } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input, Textarea } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { CompanyLogo } from '@/features/jobs/components/CompanyLogo'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { CompanyOut } from '@/lib/api'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { useUpdateMyCompany } from '../api/company'
import {
  companyProfileSchema,
  SIZE_OPTIONS,
  toCompanyPayload,
  type CompanyProfileValues,
} from '../lib/schemas'

const FIELDS = ['name', 'description', 'website', 'industry', 'size', 'location', 'logo_url'] as const

const toValues = (c: CompanyOut): CompanyProfileValues => ({
  name: c.name,
  description: c.description ?? '',
  website: c.website ?? '',
  industry: c.industry ?? '',
  size: c.size ?? '',
  location: c.location ?? '',
  logo_url: c.logo_url ?? '',
})

/** The company profile as candidates see it. Read-only (no save button, disabled controls) unless `canEdit`. */
export function CompanyProfileForm({ company, canEdit }: { company: CompanyOut; canEdit: boolean }) {
  const { user, setUser } = useAuth()
  const update = useUpdateMyCompany(company.id)
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    control,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<CompanyProfileValues>({
    resolver: zodResolver(companyProfileSchema),
    mode: 'onTouched',
    defaultValues: toValues(company),
  })
  const name = useWatch({ control, name: 'name' })
  const logo = useWatch({ control, name: 'logo_url' })

  const onSubmit = handleSubmit(
    async (values) => {
      setFormError(null)
      try {
        const saved = await update.mutateAsync(toCompanyPayload(values))
        reset(toValues(saved))
        // Keep the company shown in the account menu in sync.
        if (user?.company)
          setUser({
            ...user,
            company: { ...user.company, name: saved.name, slug: saved.slug, logo_url: saved.logo_url },
          })
        toast.success('Company profile saved')
      } catch (e) {
        setFormError(
          applyApiErrors(e, setError, { fields: FIELDS, codeFields: { COMPANY_NAME_TAKEN: 'name' } }),
        )
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>Company profile</CardTitle>
        <CardDescription>This is what candidates see on your job postings and company page.</CardDescription>
      </CardHeader>
      <CardContent>
        {!canEdit && (
          <Alert variant="info" className="mb-4" title="View only">
            <span className="flex items-center gap-1.5">
              <Lock className="size-3.5 shrink-0" aria-hidden />
              Only company administrators can edit the profile. Ask one of them to make changes.
            </span>
          </Alert>
        )}
        <form onSubmit={onSubmit} noValidate className="grid gap-4" aria-label="Company profile">
          {formError && <Alert variant="danger">{formError}</Alert>}
          <fieldset disabled={!canEdit} className="m-0 grid min-w-0 gap-4 border-0 p-0">
            <div className="flex items-center gap-4">
              <CompanyLogo name={name || company.name} logoUrl={logo || null} size="lg" />
              <p className="text-sm text-muted-foreground">
                Logos are linked by address; uploads are not supported. Use a square image served over https.
              </p>
            </div>
            <Field label="Company name" error={errors.name?.message} required>
              <Input autoComplete="organization" {...register('name')} />
            </Field>
            <Field
              label="Description"
              error={errors.description?.message}
              optional
              hint="Up to 5,000 characters."
            >
              <Textarea rows={5} {...register('description')} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Website" error={errors.website?.message} optional>
                <Input inputMode="url" placeholder="https://example.com" {...register('website')} />
              </Field>
              <Field label="Logo address" error={errors.logo_url?.message} optional>
                <Input inputMode="url" placeholder="https://example.com/logo.png" {...register('logo_url')} />
              </Field>
              <Field label="Industry" error={errors.industry?.message} optional>
                <Input {...register('industry')} />
              </Field>
              <Field label="Company size" htmlFor="cp-size" error={errors.size?.message} optional>
                <Controller
                  control={control}
                  name="size"
                  render={({ field }) => (
                    <SimpleSelect
                      id="cp-size"
                      value={field.value}
                      onValueChange={field.onChange}
                      options={SIZE_OPTIONS}
                      emptyLabel="Not specified"
                      disabled={!canEdit}
                    />
                  )}
                />
              </Field>
              <Field label="Location" error={errors.location?.message} optional className="sm:col-span-2">
                <Input autoComplete="off" placeholder="Berlin, Germany" {...register('location')} />
              </Field>
            </div>
          </fieldset>
          {canEdit && (
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!isDirty || isSubmitting}
                onClick={() => {
                  reset(toValues(company))
                  setFormError(null)
                }}
              >
                Discard changes
              </Button>
              <Button type="submit" loading={isSubmitting} disabled={!isDirty}>
                Save changes
              </Button>
            </div>
          )}
        </form>
      </CardContent>
    </Card>
  )
}
