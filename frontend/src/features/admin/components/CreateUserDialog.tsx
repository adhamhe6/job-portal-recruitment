import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { PasswordInput, PasswordRules } from '@/components/common/PasswordInput'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { ROLE_LABELS } from '@/lib/enums'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { useCompanyOptions } from '../api/companies'
import { useCreateUser } from '../api/users'
import { isStaffRole } from '../lib/labels'
import { createUserSchema, type CreateUserValues } from '../lib/schemas'

const ROLE_OPTIONS = (['CANDIDATE', 'RECRUITER', 'HIRING_MANAGER', 'ADMIN'] as const).map((value) => ({
  value,
  label: ROLE_LABELS[value],
}))

const FIELDS = ['first_name', 'last_name', 'email', 'phone', 'role', 'company_id', 'password'] as const

/**
 * Create an account with any role (POST /users). The API has no e-mail invitation flow: the administrator sets an
 * initial password and shares it out of band. The password is never echoed back, stored or logged.
 */
export function CreateUserDialog({
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
          <DialogTitle>Create user</DialogTitle>
          <DialogDescription>
            Accounts are created directly. Share the initial password through a secure channel and ask the
            person to change it after their first sign-in.
          </DialogDescription>
        </DialogHeader>
        <CreateUserForm onDone={() => onOpenChange(false)} onCancel={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

function CreateUserForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const create = useCreateUser()
  const companies = useCompanyOptions()
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    control,
    handleSubmit,
    setError,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<CreateUserValues>({
    resolver: zodResolver(createUserSchema),
    mode: 'onTouched',
    defaultValues: {
      first_name: '',
      last_name: '',
      email: '',
      phone: '',
      role: 'RECRUITER',
      company_id: '',
      password: '',
    },
  })
  const role = useWatch({ control, name: 'role' })
  const password = useWatch({ control, name: 'password' })
  const staff = isStaffRole(role)

  const onSubmit = handleSubmit(
    async (v) => {
      setFormError(null)
      try {
        const user = await create.mutateAsync({
          email: v.email.trim(),
          password: v.password,
          first_name: v.first_name.trim(),
          last_name: v.last_name.trim(),
          phone: v.phone.trim() || null,
          role: v.role,
          company_id: isStaffRole(v.role) ? v.company_id : null,
        })
        toast.success(
          `${user.first_name} ${user.last_name} was added as ${ROLE_LABELS[user.role].toLowerCase()}`,
        )
        onDone()
      } catch (e) {
        setFormError(
          applyApiErrors(e, setError, {
            fields: FIELDS,
            codeFields: {
              EMAIL_ALREADY_REGISTERED: 'email',
              COMPANY_REQUIRED: 'company_id',
              COMPANY_NOT_FOUND: 'company_id',
            },
          }),
        )
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <form onSubmit={onSubmit} noValidate className="grid gap-4" aria-label="Create user">
      {formError && <Alert variant="danger">{formError}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="First name" error={errors.first_name?.message} required>
          <Input autoComplete="off" {...register('first_name')} />
        </Field>
        <Field label="Last name" error={errors.last_name?.message} required>
          <Input autoComplete="off" {...register('last_name')} />
        </Field>
      </div>
      <Field label="Email" error={errors.email?.message} required>
        <Input type="email" autoComplete="off" {...register('email')} />
      </Field>
      <Field label="Phone" error={errors.phone?.message} optional>
        <Input type="tel" autoComplete="off" {...register('phone')} />
      </Field>
      <Field label="Role" error={errors.role?.message} required>
        <Controller
          control={control}
          name="role"
          render={({ field }) => (
            <SimpleSelect
              value={field.value}
              onValueChange={(v) => {
                field.onChange(v)
                if (!isStaffRole(v)) setValue('company_id', '')
              }}
              options={ROLE_OPTIONS}
            />
          )}
        />
      </Field>
      {staff && (
        <Field
          label="Company"
          error={errors.company_id?.message}
          hint="Recruiters and hiring managers always belong to a company."
          required
        >
          <Controller
            control={control}
            name="company_id"
            render={({ field }) => (
              <Combobox
                value={field.value}
                onChange={field.onChange}
                options={(companies.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
                placeholder={companies.isPending ? 'Loading companies…' : 'Choose a company'}
                searchPlaceholder="Search companies…"
                emptyText="No companies found"
              />
            )}
          />
        </Field>
      )}
      <Field label="Initial password" error={errors.password?.message} required>
        <PasswordInput autoComplete="new-password" {...register('password')} />
      </Field>
      <PasswordRules value={password ?? ''} />
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="outline" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" loading={isSubmitting}>
          Create user
        </Button>
      </div>
    </form>
  )
}
