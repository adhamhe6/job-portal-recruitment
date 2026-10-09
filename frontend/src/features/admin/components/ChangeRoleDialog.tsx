import { useState } from 'react'
import { toast } from 'sonner'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { SimpleSelect } from '@/components/ui/select'
import { ApiError, errorMessage, type Role } from '@/lib/api'
import { ROLE_LABELS } from '@/lib/enums'
import { useCompanyOptions } from '../api/companies'
import { useUpdateUser } from '../api/users'
import type { AdminUser } from '../api/types'
import { isStaffRole } from '../lib/labels'

const ROLE_OPTIONS = (['CANDIDATE', 'RECRUITER', 'HIRING_MANAGER', 'ADMIN'] as const).map((value) => ({
  value,
  label: ROLE_LABELS[value],
}))

/** Plain-language explanation of PATCH /users failures. */
export function describeUserUpdateError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'SELF_MODIFICATION')
      return 'You cannot suspend or change the role of your own account. Ask another administrator.'
    if (error.code === 'COMPANY_REQUIRED') return 'Recruiters and hiring managers must belong to a company.'
    if (error.status === 404) return 'This user no longer exists. Refresh the list.'
  }
  return errorMessage(error)
}

/** Change a user's role (and company, which staff roles require). */
export function ChangeRoleDialog({
  user,
  onOpenChange,
}: {
  user: AdminUser | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={user !== null} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        {user && <ChangeRoleForm key={user.id} user={user} onClose={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function ChangeRoleForm({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const update = useUpdateUser()
  const companies = useCompanyOptions()
  const [role, setRole] = useState<Role>(user.role)
  const [companyId, setCompanyId] = useState(user.company_id ?? '')
  const [error, setError] = useState<unknown>(null)
  const staff = isStaffRole(role)
  const changed = role !== user.role || (staff && companyId !== (user.company_id ?? ''))
  const missingCompany = staff && !companyId

  const submit = async () => {
    setError(null)
    try {
      await update.mutateAsync({ id: user.id, role, company_id: staff ? companyId : null })
      toast.success(`${user.first_name} ${user.last_name} is now ${ROLE_LABELS[role].toLowerCase()}`)
      onClose()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Change role</DialogTitle>
        <DialogDescription>
          {user.first_name} {user.last_name} ({user.email}) is currently{' '}
          {ROLE_LABELS[user.role].toLowerCase()}. Their permissions change the next time their session
          refreshes.
        </DialogDescription>
      </DialogHeader>
      <div className="grid gap-4">
        {error !== null && <Alert variant="danger">{describeUserUpdateError(error)}</Alert>}
        <Field label="Role">
          <SimpleSelect value={role} onValueChange={(v) => setRole(v as Role)} options={ROLE_OPTIONS} />
        </Field>
        {staff && (
          <Field label="Company" hint="Required for recruiters and hiring managers." required>
            <Combobox
              value={companyId}
              onChange={setCompanyId}
              options={(companies.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
              placeholder={companies.isPending ? 'Loading companies…' : 'Choose a company'}
              searchPlaceholder="Search companies…"
              emptyText="No companies found"
            />
          </Field>
        )}
        {!staff && user.company_id && (
          <p className="text-sm text-muted-foreground">
            Only recruiters and hiring managers belong to a company, so the company assignment will be
            removed.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={update.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} loading={update.isPending} disabled={!changed || missingCompany}>
            Save role
          </Button>
        </div>
      </div>
    </>
  )
}
