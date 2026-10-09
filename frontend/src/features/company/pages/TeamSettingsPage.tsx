import { Lock, MoreHorizontal, Pencil, UserCheck, UserPlus, UserX, Users } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { DataTable, type Column } from '@/components/common/DataTable'
import { EmptyState } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { AccountStatusBadge } from '@/features/admin/components/StatusPills'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useCompanyMembers } from '@/features/companies/api/companies'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import type { MemberOut } from '@/lib/api'
import { ROLE_LABELS } from '@/lib/enums'
import { dates } from '@/lib/format'
import { pluralize } from '@/lib/utils'
import { useUpdateMember } from '../api/company'
import { AddMemberDialog } from '../components/AddMemberDialog'
import { describeMemberError, EditMemberDialog } from '../components/EditMemberDialog'

export default function TeamSettingsPage() {
  useDocumentTitle('Team')
  const { user } = useAuth()
  const companyId = user?.company_id ?? null
  const members = useCompanyMembers(companyId)
  // Only company administrators (recruiters flagged as such) and platform administrators change the team.
  const canManage = Boolean(
    user && (user.role === 'ADMIN' || (user.role === 'RECRUITER' && user.is_company_admin)),
  )

  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<MemberOut | null>(null)
  const [statusTarget, setStatusTarget] = useState<MemberOut | null>(null)

  if (!companyId)
    return (
      <EmptyState
        icon={<Users aria-hidden />}
        title="Your account is not attached to a company"
        description="Team management is available to employer accounts."
      />
    )

  const nameOf = (m: MemberOut) => `${m.first_name} ${m.last_name}`

  const Actions = ({ m }: { m: MemberOut }) => {
    if (!canManage) return null
    if (m.id === user?.id) return <span className="text-xs text-muted-foreground">You</span>
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${nameOf(m)}`}>
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-52">
          <DropdownMenuItem onSelect={() => setEditing(m)}>
            <Pencil /> Edit role and details…
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          {m.status === 'ACTIVE' ? (
            <DropdownMenuItem destructive onSelect={() => setStatusTarget(m)}>
              <UserX /> Deactivate…
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onSelect={() => setStatusTarget(m)}>
              <UserCheck /> Reactivate…
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }

  const columns: Column<MemberOut>[] = [
    {
      key: 'member',
      header: 'Member',
      cell: (m) => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={nameOf(m)} size="sm" />
          <div className="min-w-0">
            <p className="truncate font-medium">
              {nameOf(m)}
              {m.id === user?.id && (
                <span className="ml-1.5 text-xs font-normal text-muted-foreground">(you)</span>
              )}
            </p>
            <p className="truncate text-xs text-muted-foreground">{m.email}</p>
          </div>
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Role',
      cell: (m) => (
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline">{ROLE_LABELS[m.role]}</Badge>
          {m.is_company_admin && <Badge variant="violet">Company admin</Badge>}
        </div>
      ),
    },
    {
      key: 'title',
      header: 'Title',
      hideBelow: 'lg',
      cell: (m) =>
        [m.job_title, m.department].filter(Boolean).join(' · ') || (
          <span className="text-muted-foreground">—</span>
        ),
    },
    { key: 'status', header: 'Status', cell: (m) => <AccountStatusBadge status={m.status} /> },
    {
      key: 'login',
      header: 'Last sign-in',
      hideBelow: 'md',
      cell: (m) =>
        m.last_login_at ? (
          dates.relative(m.last_login_at)
        ) : (
          <span className="text-muted-foreground">Never</span>
        ),
    },
    ...(canManage
      ? [
          {
            key: 'actions',
            header: <span className="sr-only">Actions</span>,
            align: 'right' as const,
            cell: (m: MemberOut) => <Actions m={m} />,
          },
        ]
      : []),
  ]

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between sm:space-y-0">
          <div className="grid gap-1">
            <CardTitle>Team</CardTitle>
            <CardDescription>
              Recruiters and hiring managers in {user?.company?.name ?? 'your company'}
              {members.data ? ` (${pluralize(members.data.length, 'member')})` : ''}.
            </CardDescription>
          </div>
          {canManage && (
            <Button onClick={() => setAdding(true)}>
              <UserPlus /> Add member
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          {!canManage && (
            <Alert variant="info" title="View only">
              <span className="flex items-center gap-1.5">
                <Lock className="size-3.5 shrink-0" aria-hidden />
                Only company administrators can add members or change roles.
              </span>
            </Alert>
          )}
          <div className="-mx-6 -mb-6 border-t">
            <DataTable
              caption="Team members"
              rows={members.data}
              rowKey={(m) => m.id}
              columns={columns}
              loading={members.isPending}
              error={members.isError ? members.error : undefined}
              onRetry={() => members.refetch()}
              renderCard={(m) => (
                <div className="flex items-start gap-3 p-4">
                  <Avatar name={nameOf(m)} size="sm" />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <p className="truncate font-medium">
                      {nameOf(m)}
                      {m.id === user?.id && (
                        <span className="ml-1.5 text-xs font-normal text-muted-foreground">(you)</span>
                      )}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{m.email}</p>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline">{ROLE_LABELS[m.role]}</Badge>
                      {m.is_company_admin && <Badge variant="violet">Company admin</Badge>}
                      <AccountStatusBadge status={m.status} />
                    </div>
                    {(m.job_title || m.department) && (
                      <p className="text-xs text-muted-foreground">
                        {[m.job_title, m.department].filter(Boolean).join(' · ')}
                      </p>
                    )}
                  </div>
                  <Actions m={m} />
                </div>
              )}
              empty={
                <EmptyState
                  icon={<Users aria-hidden />}
                  title="No team members yet"
                  description="Add recruiters and hiring managers so they can work on your jobs."
                  action={canManage ? <Button onClick={() => setAdding(true)}>Add member</Button> : undefined}
                />
              }
            />
          </div>
        </CardContent>
      </Card>

      <AddMemberDialog companyId={companyId} open={adding} onOpenChange={setAdding} />
      <EditMemberDialog companyId={companyId} member={editing} onOpenChange={(o) => !o && setEditing(null)} />
      <MemberStatusDialog companyId={companyId} member={statusTarget} onClose={() => setStatusTarget(null)} />
    </div>
  )
}

function MemberStatusDialog({
  companyId,
  member,
  onClose,
}: {
  companyId: string
  member: MemberOut | null
  onClose: () => void
}) {
  const update = useUpdateMember(companyId)
  const [error, setError] = useState<unknown>(null)
  const [shown, setShown] = useState<MemberOut | null>(member)
  if (member && member !== shown) setShown(member)
  const target = member ?? shown
  const suspending = target?.status === 'ACTIVE'
  const name = target ? `${target.first_name} ${target.last_name}` : ''

  const close = () => {
    setError(null)
    onClose()
  }
  const confirm = async () => {
    if (!target) return
    setError(null)
    try {
      await update.mutateAsync({ userId: target.id, status: suspending ? 'SUSPENDED' : 'ACTIVE' })
      toast.success(`${name} was ${suspending ? 'deactivated' : 'reactivated'}`)
      onClose()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <ConfirmDialog
      open={member !== null}
      onOpenChange={(o) => !o && close()}
      title={suspending ? `Deactivate ${name}?` : `Reactivate ${name}?`}
      description={
        suspending
          ? 'They are signed out everywhere and can no longer access your company until you reactivate them. Jobs and notes they created are kept.'
          : 'They can sign in and work on your company again.'
      }
      confirmLabel={suspending ? 'Deactivate' : 'Reactivate'}
      destructive={suspending}
      loading={update.isPending}
      onConfirm={confirm}
    >
      {error !== null && <Alert variant="danger">{describeMemberError(error)}</Alert>}
    </ConfirmDialog>
  )
}
