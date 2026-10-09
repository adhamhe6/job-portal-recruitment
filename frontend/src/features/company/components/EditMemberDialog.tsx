import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { SimpleSelect } from '@/components/ui/select'
import { ApiError, errorMessage, type MemberOut } from '@/lib/api'
import { applyApiErrors } from '@/lib/forms'
import { useUpdateMember } from '../api/company'
import { editMemberSchema, type EditMemberValues } from '../lib/schemas'
import { MEMBER_ROLE_OPTIONS } from './AddMemberDialog'

export function describeMemberError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'SELF_MODIFICATION') return 'You cannot suspend or change the role of your own account.'
    if (e.status === 403) return 'Only company administrators can change the team.'
    if (e.status === 404) return 'This member no longer exists. Refresh the page.'
  }
  return errorMessage(e)
}

export function EditMemberDialog({
  companyId,
  member,
  onOpenChange,
}: {
  companyId: string
  member: MemberOut | null
  onOpenChange: (o: boolean) => void
}) {
  return (
    <Dialog open={member !== null} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        {member && (
          <Form key={member.id} companyId={companyId} member={member} onClose={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function Form({ companyId, member, onClose }: { companyId: string; member: MemberOut; onClose: () => void }) {
  const update = useUpdateMember(companyId)
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<EditMemberValues>({
    resolver: zodResolver(editMemberSchema),
    defaultValues: {
      role: member.role === 'HIRING_MANAGER' ? 'HIRING_MANAGER' : 'RECRUITER',
      job_title: member.job_title ?? '',
      department: member.department ?? '',
    },
  })
  const name = `${member.first_name} ${member.last_name}`

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null)
    try {
      await update.mutateAsync({
        userId: member.id,
        role: v.role,
        job_title: v.job_title.trim(),
        department: v.department.trim(),
      })
      toast.success(`${name} was updated`)
      onClose()
    } catch (e) {
      setFormError(
        applyApiErrors(e, setError, { fields: ['role', 'job_title', 'department'] }) ??
          describeMemberError(e),
      )
    }
  })

  return (
    <>
      <DialogHeader>
        <DialogTitle>Edit {name}</DialogTitle>
        <DialogDescription>{member.email}</DialogDescription>
      </DialogHeader>
      <form onSubmit={onSubmit} noValidate className="grid gap-4" aria-label={`Edit ${name}`}>
        {formError && <Alert variant="danger">{formError}</Alert>}
        <Field
          label="Role"
          htmlFor="em-role"
          hint={member.is_company_admin ? 'Company administrators stay recruiters.' : undefined}
          error={errors.role?.message}
        >
          <Controller
            control={control}
            name="role"
            render={({ field }) => (
              <SimpleSelect
                id="em-role"
                value={field.value}
                onValueChange={field.onChange}
                options={MEMBER_ROLE_OPTIONS}
                disabled={member.is_company_admin}
              />
            )}
          />
        </Field>
        <Field label="Job title" error={errors.job_title?.message} optional>
          <Input {...register('job_title')} />
        </Field>
        <Field label="Department" error={errors.department?.message} optional>
          <Input {...register('department')} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" loading={isSubmitting} disabled={!isDirty}>
            Save changes
          </Button>
        </div>
      </form>
    </>
  )
}
