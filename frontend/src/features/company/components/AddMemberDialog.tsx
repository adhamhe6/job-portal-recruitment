import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { PasswordInput, PasswordRules } from '@/components/common/PasswordInput'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { ROLE_LABELS } from '@/lib/enums'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { useAddMember } from '../api/company'
import { addMemberSchema, MEMBER_ROLES, type AddMemberValues } from '../lib/schemas'

export const MEMBER_ROLE_OPTIONS = MEMBER_ROLES.map((value) => ({ value, label: ROLE_LABELS[value] }))
const FIELDS = [
  'first_name',
  'last_name',
  'email',
  'phone',
  'role',
  'job_title',
  'department',
  'password',
] as const

/** Add a recruiter or hiring manager. The API creates the account directly (no e-mail invitation): the admin sets the first password. */
export function AddMemberDialog({
  companyId,
  open,
  onOpenChange,
}: {
  companyId: string
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Add team member</DialogTitle>
          <DialogDescription>
            There is no e-mail invitation: the account is created now. Share the initial password through a
            secure channel and ask them to change it after signing in.
          </DialogDescription>
        </DialogHeader>
        <Form companyId={companyId} onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

function Form({ companyId, onClose }: { companyId: string; onClose: () => void }) {
  const add = useAddMember(companyId)
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<AddMemberValues>({
    resolver: zodResolver(addMemberSchema),
    mode: 'onTouched',
    defaultValues: {
      first_name: '',
      last_name: '',
      email: '',
      phone: '',
      role: 'RECRUITER',
      job_title: '',
      department: '',
      password: '',
    },
  })
  const password = useWatch({ control, name: 'password' })

  const onSubmit = handleSubmit(
    async (v) => {
      setFormError(null)
      try {
        const m = await add.mutateAsync({
          email: v.email.trim(),
          password: v.password,
          first_name: v.first_name.trim(),
          last_name: v.last_name.trim(),
          phone: v.phone.trim() || null,
          role: v.role,
          job_title: v.job_title.trim() || null,
          department: v.department.trim() || null,
        })
        toast.success(`${m.first_name} ${m.last_name} was added as ${ROLE_LABELS[m.role].toLowerCase()}`)
        onClose()
      } catch (e) {
        setFormError(
          applyApiErrors(e, setError, { fields: FIELDS, codeFields: { EMAIL_ALREADY_REGISTERED: 'email' } }),
        )
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <form onSubmit={onSubmit} noValidate className="grid gap-4" aria-label="Add team member">
      {formError && <Alert variant="danger">{formError}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="First name" error={errors.first_name?.message} required>
          <Input autoComplete="off" {...register('first_name')} />
        </Field>
        <Field label="Last name" error={errors.last_name?.message} required>
          <Input autoComplete="off" {...register('last_name')} />
        </Field>
      </div>
      <Field label="Work email" error={errors.email?.message} required>
        <Input type="email" autoComplete="off" {...register('email')} />
      </Field>
      <Field label="Phone" error={errors.phone?.message} optional>
        <Input type="tel" autoComplete="off" {...register('phone')} />
      </Field>
      <Field
        label="Role"
        htmlFor="am-role"
        error={errors.role?.message}
        hint="Recruiters manage jobs and candidates; hiring managers review the jobs assigned to them."
        required
      >
        <Controller
          control={control}
          name="role"
          render={({ field }) => (
            <SimpleSelect
              id="am-role"
              value={field.value}
              onValueChange={field.onChange}
              options={MEMBER_ROLE_OPTIONS}
            />
          )}
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Job title" error={errors.job_title?.message} optional>
          <Input {...register('job_title')} />
        </Field>
        <Field label="Department" error={errors.department?.message} optional>
          <Input {...register('department')} />
        </Field>
      </div>
      <Field label="Initial password" error={errors.password?.message} required>
        <PasswordInput autoComplete="new-password" {...register('password')} />
      </Field>
      <PasswordRules value={password ?? ''} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onClose} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" loading={isSubmitting}>
          Add member
        </Button>
      </div>
    </form>
  )
}
