import { ScrollText } from 'lucide-react'
import { DataTable, type Column } from '@/components/common/DataTable'
import { DebouncedInput } from '@/components/common/DebouncedInput'
import { EmptyState, NoResults } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SimpleSelect } from '@/components/ui/select'
import { dates } from '@/lib/format'
import { useAuditLog, type AuditFilters, type Polling } from '../api/admin'
import type { AuditEvent } from '../api/types'
import { AUDIT_ENTITY_OPTIONS, describeAction, summarizeMetadata } from '../lib/labels'

export type AuditPatch = Partial<{ action: string; entity: string; from: string; to: string; apage: number }>

export function AuditPanel({
  filters,
  onFilters,
  polling,
}: {
  filters: AuditFilters
  onFilters: (patch: AuditPatch) => void
  polling: Polling
}) {
  const query = useAuditLog(filters, polling)
  const filtered = Boolean(filters.action || filters.entityType || filters.from || filters.to)

  const columns: Column<AuditEvent>[] = [
    {
      key: 'when',
      header: 'When',
      cell: (e) => (
        <time dateTime={e.created_at} title={dates.dateTime(e.created_at)} className="whitespace-nowrap">
          {dates.dateTime(e.created_at)}
        </time>
      ),
    },
    {
      key: 'actor',
      header: 'Actor',
      cell: (e) =>
        e.actor_name || e.actor_email ? (
          <div className="min-w-0">
            <p className="truncate">{e.actor_name ?? e.actor_email}</p>
            {e.actor_name && e.actor_email && (
              <p className="truncate text-xs text-muted-foreground">{e.actor_email}</p>
            )}
          </div>
        ) : (
          <span className="text-muted-foreground">System</span>
        ),
    },
    {
      key: 'action',
      header: 'Action',
      cell: (e) => (
        <div>
          <p className="font-medium">{describeAction(e.action)}</p>
          <p className="font-mono text-xs text-muted-foreground">{e.action}</p>
        </div>
      ),
    },
    {
      key: 'entity',
      header: 'Entity',
      hideBelow: 'md',
      cell: (e) => (
        <span>
          {e.entity_type}
          {e.entity_id && (
            <span className="ml-1 font-mono text-xs text-muted-foreground">{e.entity_id.slice(0, 8)}</span>
          )}
        </span>
      ),
    },
    {
      key: 'details',
      header: 'Details',
      hideBelow: 'lg',
      cell: (e) => (
        <span className="text-xs text-muted-foreground">{summarizeMetadata(e.metadata) || '—'}</span>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="audit-action">Action</Label>
          <DebouncedInput
            id="audit-action"
            value={filters.action}
            onValueChange={(action) => onFilters({ action })}
            placeholder="job.* or user.created"
            className="w-56"
            maxLength={80}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="audit-entity">Entity</Label>
          <SimpleSelect
            id="audit-entity"
            value={filters.entityType}
            onValueChange={(entity) => onFilters({ entity })}
            options={AUDIT_ENTITY_OPTIONS}
            emptyLabel="Any entity"
            className="w-40"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="audit-from">From</Label>
          <Input
            id="audit-from"
            type="date"
            value={filters.from}
            max={filters.to || undefined}
            onChange={(e) => onFilters({ from: e.target.value })}
            className="w-40"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="audit-to">To</Label>
          <Input
            id="audit-to"
            type="date"
            value={filters.to}
            min={filters.from || undefined}
            onChange={(e) => onFilters({ to: e.target.value })}
            className="w-40"
          />
        </div>
        {filtered && (
          <Button
            variant="link"
            size="sm"
            onClick={() => onFilters({ action: '', entity: '', from: '', to: '' })}
          >
            Clear filters
          </Button>
        )}
      </div>
      <Card className="overflow-hidden p-0">
        <DataTable
          caption="Audit events, newest first"
          rows={query.data?.items}
          rowKey={(e) => e.id}
          columns={columns}
          loading={query.isFetching && !query.data}
          error={query.isError && !query.data ? query.error : undefined}
          onRetry={() => query.refetch()}
          page={query.data?.page}
          pages={query.data?.pages}
          total={query.data?.total}
          pageSize={filters.pageSize}
          onPageChange={(apage) => onFilters({ apage })}
          renderCard={(e) => (
            <div className="space-y-1 p-4">
              <p className="font-medium">{describeAction(e.action)}</p>
              <p className="text-xs text-muted-foreground">
                {e.actor_name ?? e.actor_email ?? 'System'} · {dates.dateTime(e.created_at)}
              </p>
              <p className="font-mono text-xs text-muted-foreground">
                {e.action} · {e.entity_type}
              </p>
              {summarizeMetadata(e.metadata) && (
                <p className="text-xs text-muted-foreground">{summarizeMetadata(e.metadata)}</p>
              )}
            </div>
          )}
          empty={
            filtered ? (
              <NoResults
                title="No audit events match these filters"
                description="Use an exact action or a prefix ending in *, for example interview.*"
              />
            ) : (
              <EmptyState
                icon={<ScrollText aria-hidden />}
                title="No audit events yet"
                description="Business actions are recorded here as they happen."
              />
            )
          }
        />
      </Card>
    </div>
  )
}
