import { Building2, MoreHorizontal, Plus, Power, PowerOff, Eye } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { DataTable, type Column } from '@/components/common/DataTable'
import { FilterBar, type ActiveFilter } from '@/components/common/FilterBar'
import { PageHeader } from '@/components/common/PageHeader'
import { SearchInput } from '@/components/common/SearchInput'
import { EmptyState, NoResults } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { SimpleSelect } from '@/components/ui/select'
import { CompanyLogo } from '@/features/jobs/components/CompanyLogo'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { ApiError, errorMessage } from '@/lib/api'
import { dates } from '@/lib/format'
import { useAdminCompanies, useUpdateAdminCompany } from '../api/companies'
import type { AdminCompany } from '../api/types'
import { CompanyDetailsSheet } from '../components/CompanyDetailsSheet'
import { CreateCompanyDialog } from '../components/CreateCompanyDialog'
import { AccountStatusBadge } from '../components/StatusPills'
import { ACCOUNT_STATUS_OPTIONS } from '../lib/labels'

const PAGE_SIZE = 20

export default function CompaniesPage() {
  useDocumentTitle('Companies')
  const [filters, update, reset] = useUrlState({ q: '', status: '', page: 1 })
  const query = useAdminCompanies({ ...filters, pageSize: PAGE_SIZE })
  const [creating, setCreating] = useState(false)
  const [detailsId, setDetailsId] = useState<string | null>(null)
  const [statusTarget, setStatusTarget] = useState<AdminCompany | null>(null)

  // The panel reads the live row from the list, so a status change is reflected immediately after refetch.
  const details = query.data?.items.find((c) => c.id === detailsId) ?? null

  const active: ActiveFilter[] = [
    filters.q && { key: 'q', label: `Search: ${filters.q}`, onRemove: () => update({ q: '' }) },
    filters.status && {
      key: 'status',
      label: `Status: ${filters.status === 'ACTIVE' ? 'Active' : 'Suspended'}`,
      onRemove: () => update({ status: '' }),
    },
  ].filter(Boolean) as ActiveFilter[]

  const actions = (c: AdminCompany) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${c.name}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-52">
        <DropdownMenuItem onSelect={() => setDetailsId(c.id)}>
          <Eye /> View details
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {c.status === 'ACTIVE' ? (
          <DropdownMenuItem destructive onSelect={() => setStatusTarget(c)}>
            <PowerOff /> Suspend…
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onSelect={() => setStatusTarget(c)}>
            <Power /> Reactivate…
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )

  const columns: Column<AdminCompany>[] = [
    {
      key: 'name',
      header: 'Company',
      cell: (c) => (
        <div className="flex min-w-0 items-center gap-3">
          <CompanyLogo name={c.name} logoUrl={c.logo_url} size="sm" />
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => setDetailsId(c.id)}
              className="block max-w-full cursor-pointer truncate rounded-sm text-left font-medium hover:underline"
            >
              {c.name}
            </button>
            <p className="truncate text-xs text-muted-foreground">{c.industry ?? c.slug}</p>
          </div>
        </div>
      ),
    },
    { key: 'location', header: 'Location', hideBelow: 'lg', cell: (c) => c.location ?? '—' },
    { key: 'size', header: 'Size', hideBelow: 'lg', cell: (c) => c.size ?? '—' },
    { key: 'status', header: 'Status', cell: (c) => <AccountStatusBadge status={c.status} /> },
    { key: 'created', header: 'Created', hideBelow: 'md', cell: (c) => dates.date(c.created_at) },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (c) => actions(c),
    },
  ]

  return (
    <>
      <PageHeader
        title="Companies"
        description="Tenant companies on the platform. Suspend a company to hide its jobs from candidates and stop new publishing."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> Create company
          </Button>
        }
      />
      <div className="space-y-4">
        <FilterBar active={active} onClearAll={() => reset()}>
          <SearchInput
            value={filters.q}
            onChange={(q) => update({ q })}
            placeholder="Search companies"
            label="Search companies"
            className="w-full sm:w-72"
          />
          <SimpleSelect
            aria-label="Filter by status"
            value={filters.status}
            onValueChange={(status) => update({ status })}
            options={ACCOUNT_STATUS_OPTIONS}
            emptyLabel="Any status"
            className="w-40"
          />
        </FilterBar>
        <Card className="overflow-hidden p-0">
          <DataTable
            caption="Companies"
            rows={query.data?.items}
            rowKey={(c) => c.id}
            columns={columns}
            loading={query.isFetching}
            error={query.isError && !query.data ? query.error : undefined}
            onRetry={() => query.refetch()}
            page={query.data?.page}
            pages={query.data?.pages}
            total={query.data?.total}
            pageSize={PAGE_SIZE}
            onPageChange={(page) => update({ page }, { resetPage: false })}
            renderCard={(c) => (
              <div className="flex items-start gap-3 p-4">
                <CompanyLogo name={c.name} logoUrl={c.logo_url} size="sm" />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <button
                    type="button"
                    onClick={() => setDetailsId(c.id)}
                    className="block max-w-full cursor-pointer truncate rounded-sm text-left font-medium hover:underline"
                  >
                    {c.name}
                  </button>
                  <p className="truncate text-xs text-muted-foreground">
                    {[c.industry, c.location].filter(Boolean).join(' · ') || c.slug}
                  </p>
                  <AccountStatusBadge status={c.status} />
                </div>
                {actions(c)}
              </div>
            )}
            empty={
              active.length > 0 ? (
                <NoResults
                  title="No companies match these filters"
                  action={
                    <Button variant="outline" onClick={() => reset()}>
                      Clear filters
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon={<Building2 aria-hidden />}
                  title="No companies yet"
                  description="Create the first tenant company."
                  action={<Button onClick={() => setCreating(true)}>Create company</Button>}
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

      <CreateCompanyDialog open={creating} onOpenChange={setCreating} />
      <CompanyDetailsSheet
        company={details}
        onOpenChange={(o) => !o && setDetailsId(null)}
        onToggleStatus={setStatusTarget}
      />
      <CompanyStatusDialog company={statusTarget} onClose={() => setStatusTarget(null)} />
    </>
  )
}

function CompanyStatusDialog({ company, onClose }: { company: AdminCompany | null; onClose: () => void }) {
  const update = useUpdateAdminCompany()
  const [error, setError] = useState<unknown>(null)
  const [shown, setShown] = useState<AdminCompany | null>(company)
  if (company && company !== shown) setShown(company)
  const target = company ?? shown
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
      toast.success(`${target.name} was ${suspending ? 'suspended' : 'reactivated'}`)
      onClose()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <ConfirmDialog
      open={company !== null}
      onOpenChange={(o) => !o && close()}
      title={
        suspending ? `Suspend ${target?.name ?? 'company'}?` : `Reactivate ${target?.name ?? 'company'}?`
      }
      description={
        suspending
          ? 'Its jobs are hidden from candidates, cannot receive applications or matches, and it cannot publish new jobs until you reactivate it. Nothing is deleted.'
          : 'Its published jobs become visible to candidates again and it can publish new jobs.'
      }
      confirmLabel={suspending ? 'Suspend company' : 'Reactivate company'}
      destructive={suspending}
      loading={update.isPending}
      onConfirm={confirm}
    >
      {error !== null && (
        <Alert variant="danger">
          {error instanceof ApiError && error.status === 404
            ? 'This company no longer exists. Refresh the list.'
            : errorMessage(error)}
        </Alert>
      )}
    </ConfirmDialog>
  )
}
