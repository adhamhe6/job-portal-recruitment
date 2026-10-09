import { UserPlus, Users } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { DataTable, type Column } from '@/components/common/DataTable'
import { FilterBar, type ActiveFilter } from '@/components/common/FilterBar'
import { PageHeader } from '@/components/common/PageHeader'
import { SearchInput } from '@/components/common/SearchInput'
import { NoResults, EmptyState } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Combobox } from '@/components/ui/combobox'
import { SimpleSelect } from '@/components/ui/select'
import { Avatar } from '@/components/ui/avatar'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { ROLE_LABELS } from '@/lib/enums'
import { dates } from '@/lib/format'
import { useCompanyOptions } from '../api/companies'
import { useAdminUsers, useUpdateUser } from '../api/users'
import type { AdminUser } from '../api/types'
import { ChangeRoleDialog, describeUserUpdateError } from '../components/ChangeRoleDialog'
import { CreateUserDialog } from '../components/CreateUserDialog'
import { AccountStatusBadge } from '../components/StatusPills'
import { UserRowActions } from '../components/UserRowActions'
import { ACCOUNT_STATUS_OPTIONS } from '../lib/labels'

const PAGE_SIZE = 20
const ROLE_OPTIONS = (Object.keys(ROLE_LABELS) as (keyof typeof ROLE_LABELS)[]).map((value) => ({
  value,
  label: ROLE_LABELS[value],
}))

export default function UsersPage() {
  useDocumentTitle('Users')
  const { user: me } = useAuth()
  const [filters, update, reset] = useUrlState({ q: '', role: '', status: '', company: '', page: 1 })
  const query = useAdminUsers({
    q: filters.q,
    role: filters.role,
    status: filters.status,
    companyId: filters.company,
    page: filters.page,
    pageSize: PAGE_SIZE,
  })
  const companies = useCompanyOptions()
  const companyName = useMemo(
    () => new Map((companies.data ?? []).map((c) => [c.id, c.name] as const)),
    [companies.data],
  )

  const [creating, setCreating] = useState(false)
  const [roleTarget, setRoleTarget] = useState<AdminUser | null>(null)
  const [statusTarget, setStatusTarget] = useState<AdminUser | null>(null)

  const active: ActiveFilter[] = [
    filters.q && { key: 'q', label: `Search: ${filters.q}`, onRemove: () => update({ q: '' }) },
    filters.role && {
      key: 'role',
      label: `Role: ${ROLE_LABELS[filters.role as keyof typeof ROLE_LABELS] ?? filters.role}`,
      onRemove: () => update({ role: '' }),
    },
    filters.status && {
      key: 'status',
      label: `Status: ${filters.status === 'ACTIVE' ? 'Active' : 'Suspended'}`,
      onRemove: () => update({ status: '' }),
    },
    filters.company && {
      key: 'company',
      label: `Company: ${companyName.get(filters.company) ?? 'selected'}`,
      onRemove: () => update({ company: '' }),
    },
  ].filter(Boolean) as ActiveFilter[]

  const nameOf = (u: AdminUser) => `${u.first_name} ${u.last_name}`
  const columns: Column<AdminUser>[] = [
    {
      key: 'user',
      header: 'User',
      cell: (u) => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={nameOf(u)} size="sm" />
          <div className="min-w-0">
            <p className="truncate font-medium">
              {nameOf(u)}
              {u.id === me?.id && (
                <span className="ml-1.5 text-xs font-normal text-muted-foreground">(you)</span>
              )}
            </p>
            <p className="truncate text-xs text-muted-foreground">{u.email}</p>
          </div>
        </div>
      ),
    },
    { key: 'role', header: 'Role', cell: (u) => <Badge variant="outline">{ROLE_LABELS[u.role]}</Badge> },
    {
      key: 'company',
      header: 'Company',
      hideBelow: 'lg',
      cell: (u) =>
        u.company_id ? (
          (companyName.get(u.company_id) ?? <span className="text-muted-foreground">Unknown company</span>)
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    { key: 'status', header: 'Status', cell: (u) => <AccountStatusBadge status={u.status} /> },
    {
      key: 'login',
      header: 'Last sign-in',
      hideBelow: 'md',
      cell: (u) =>
        u.last_login_at ? (
          dates.relative(u.last_login_at)
        ) : (
          <span className="text-muted-foreground">Never</span>
        ),
    },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (u) => (
        <UserRowActions
          user={u}
          isSelf={u.id === me?.id}
          onChangeRole={setRoleTarget}
          onToggleStatus={setStatusTarget}
        />
      ),
    },
  ]

  const hasFilters = active.length > 0
  const rows = query.data?.items

  return (
    <>
      <PageHeader
        title="Users"
        description="Search every account on the platform, change roles and suspend or reactivate access."
        actions={
          <Button onClick={() => setCreating(true)}>
            <UserPlus /> Create user
          </Button>
        }
      />
      <div className="space-y-4">
        <FilterBar active={active} onClearAll={() => reset()}>
          <SearchInput
            value={filters.q}
            onChange={(q) => update({ q })}
            placeholder="Search by name or email"
            label="Search users"
            className="w-full sm:w-72"
          />
          <SimpleSelect
            aria-label="Filter by role"
            value={filters.role}
            onValueChange={(role) => update({ role })}
            options={ROLE_OPTIONS}
            emptyLabel="All roles"
            className="w-44"
          />
          <SimpleSelect
            aria-label="Filter by status"
            value={filters.status}
            onValueChange={(status) => update({ status })}
            options={ACCOUNT_STATUS_OPTIONS}
            emptyLabel="Any status"
            className="w-40"
          />
          <Combobox
            aria-label="Filter by company"
            value={filters.company}
            onChange={(company) => update({ company })}
            options={(companies.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
            placeholder="Any company"
            searchPlaceholder="Search companies…"
            emptyText="No companies found"
            clearable
            className="w-52"
          />
        </FilterBar>

        <Card className="overflow-hidden p-0">
          <DataTable
            caption="Users"
            rows={rows}
            rowKey={(u) => u.id}
            columns={columns}
            loading={query.isFetching}
            error={query.isError && !query.data ? query.error : undefined}
            onRetry={() => query.refetch()}
            page={query.data?.page}
            pages={query.data?.pages}
            total={query.data?.total}
            pageSize={PAGE_SIZE}
            onPageChange={(page) => update({ page }, { resetPage: false })}
            renderCard={(u) => (
              <div className="flex items-start gap-3 p-4">
                <Avatar name={nameOf(u)} size="sm" />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <p className="truncate font-medium">
                    {nameOf(u)}
                    {u.id === me?.id && (
                      <span className="ml-1.5 text-xs font-normal text-muted-foreground">(you)</span>
                    )}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">{u.email}</p>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline">{ROLE_LABELS[u.role]}</Badge>
                    <AccountStatusBadge status={u.status} />
                  </div>
                  {u.company_id && (
                    <p className="text-xs text-muted-foreground">
                      {companyName.get(u.company_id) ?? 'Unknown company'}
                    </p>
                  )}
                </div>
                <UserRowActions
                  user={u}
                  isSelf={u.id === me?.id}
                  onChangeRole={setRoleTarget}
                  onToggleStatus={setStatusTarget}
                />
              </div>
            )}
            empty={
              hasFilters ? (
                <NoResults
                  title="No users match these filters"
                  description="Try a different search or clear the filters."
                  action={
                    <Button variant="outline" onClick={() => reset()}>
                      Clear filters
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon={<Users aria-hidden />}
                  title="No users yet"
                  description="Create the first account to get started."
                  action={<Button onClick={() => setCreating(true)}>Create user</Button>}
                />
              )
            }
          />
          {query.isError && query.data && (
            <div className="p-3">
              <Alert variant="danger" title="Could not refresh the list">
                Showing the last loaded results.{' '}
                <button type="button" className="font-medium underline" onClick={() => query.refetch()}>
                  Try again
                </button>
              </Alert>
            </div>
          )}
        </Card>
      </div>

      <CreateUserDialog open={creating} onOpenChange={setCreating} />
      <ChangeRoleDialog user={roleTarget} onOpenChange={(o) => !o && setRoleTarget(null)} />
      <StatusDialog user={statusTarget} onClose={() => setStatusTarget(null)} />
    </>
  )
}

function StatusDialog({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const update = useUpdateUser()
  const [error, setError] = useState<unknown>(null)
  // Keep the last target while the dialog animates closed.
  const [shown, setShown] = useState<AdminUser | null>(user)
  if (user && user !== shown) setShown(user)
  const target = user ?? shown
  const suspending = target?.status === 'ACTIVE'

  const close = () => {
    setError(null)
    onClose()
  }
  const confirm = async () => {
    if (!target) return
    setError(null)
    try {
      await update.mutateAsync({ id: target.id, status: suspending ? 'SUSPENDED' : 'ACTIVE' })
      toast.success(
        `${target.first_name} ${target.last_name} was ${suspending ? 'deactivated' : 'reactivated'}`,
      )
      onClose()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <ConfirmDialog
      open={user !== null}
      onOpenChange={(o) => !o && close()}
      title={suspending ? 'Deactivate this user?' : 'Reactivate this user?'}
      description={
        target &&
        (suspending
          ? `${target.first_name} ${target.last_name} (${target.email}) will be signed out everywhere and will not be able to sign in until reactivated. Their data is kept.`
          : `${target.first_name} ${target.last_name} (${target.email}) will be able to sign in again.`)
      }
      confirmLabel={suspending ? 'Deactivate' : 'Reactivate'}
      destructive={suspending}
      loading={update.isPending}
      onConfirm={confirm}
    >
      {error !== null && <Alert variant="danger">{describeUserUpdateError(error)}</Alert>}
    </ConfirmDialog>
  )
}
