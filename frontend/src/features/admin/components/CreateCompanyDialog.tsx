import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, Textarea } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { useCreateCompany } from '../api/companies'
import { COMPANY_SIZES, createCompanySchema, normalizeUrl, type CreateCompanyValues } from '../lib/schemas'

const SIZE_OPTIONS = COMPANY_SIZES.map((s) => ({ value: s, label: `${s} employees` }))
const FIELDS = ['name', 'industry', 'website', 'location', 'size', 'description'] as const

export function CreateCompanyDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Create company</DialogTitle>
          <DialogDescription>
            Add a tenant. Create recruiters for it afterwards from the Users page.
          </DialogDescription>
        </DialogHeader>
        <Form onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

function Form({ onClose }: { onClose: () => void }) {
  const create = useCreateCompany()
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<CreateCompanyValues>({
    resolver: zodResolver(createCompanySchema),
    mode: 'onTouched',
    defaultValues: { name: '', industry: '', website: '', location: '', size: '', description: '' },
  })

  const onSubmit = handleSubmit(
    async (v) => {
      setFormError(null)
      try {
        const c = await create.mutateAsync({
          name: v.name.trim(),
          industry: v.industry.trim() || null,
          website: normalizeUrl(v.website) || null,
          location: v.location.trim() || null,
          size: v.size || null,
          description: v.description.trim() || null,
        })
        toast.success(`${c.name} was created`)
        onClose()
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
    <form onSubmit={onSubmit} noValidate className="grid gap-4" aria-label="Create company">
      {formError && <Alert variant="danger">{formError}</Alert>}
      <Field label="Company name" error={errors.name?.message} required>
        <Input autoComplete="off" {...register('name')} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Industry" error={errors.industry?.message} optional>
          <Input {...register('industry')} />
        </Field>
        <Field label="Size" error={errors.size?.message} optional>
          <Controller
            control={control}
            name="size"
            render={({ field }) => (
              <SimpleSelect
                value={field.value}
                onValueChange={field.onChange}
                options={SIZE_OPTIONS}
                emptyLabel="Not specified"
              />
            )}
          />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Website" error={errors.website?.message} optional>
          <Input inputMode="url" placeholder="https://example.com" {...register('website')} />
        </Field>
        <Field label="Location" error={errors.location?.message} optional>
          <Input {...register('location')} />
        </Field>
      </div>
      <Field label="Description" error={errors.description?.message} optional>
        <Textarea rows={3} {...register('description')} />
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onClose} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" loading={isSubmitting}>
          Create company
        </Button>
      </div>
    </form>
  )
}
