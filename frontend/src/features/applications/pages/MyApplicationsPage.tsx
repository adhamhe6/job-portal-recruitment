import { BriefcaseBusiness } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageHeader } from '@/components/common/PageHeader'
import { EmptyState, ErrorState, NoResults } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Textarea } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { SimpleSelect } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { ApiError, errorMessage, type ApplicationListItem, type ApplicationStatus } from '@/lib/api'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { useMyApplications, useWithdrawApplication, type ApplicationSort } from '../api/myApplications'
import { ApplicationCard } from '../components/ApplicationCard'

const STATUS_OPTIONS = (Object.keys(APPLICATION_STATUS_LABELS) as ApplicationStatus[]).map((value) => ({
  value,
  label: APPLICATION_STATUS_LABELS[value],
}))
const SORT_OPTIONS: { value: ApplicationSort; label: string }[] = [
  { value: 'newest', label: 'Newest first' },
  { value: 'updated', label: 'Recently updated' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'match', label: 'Best match' },
]
const PAGE_SIZE = 10
const MAX_COMMENT = 2000

function withdrawMessage(e: unknown): string {
  if (e instanceof ApiError && e.code === 'CANNOT_WITHDRAW')
    return 'This application has moved past the screening stage, so it can no longer be withdrawn here. Please contact the recruiter.'
  return errorMessage(e)
}

function ListSkeleton() {
  return (
    <div className="grid gap-3" role="status" aria-busy="true" aria-label="Loading applications">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-36 w-full rounded-xl" />
      ))}
    </div>
  )
}

export default function MyApplicationsPage() {
  useDocumentTitle('My applications')
  const [{ status, sort, page }, update] = useUrlState({ status: '', sort: 'newest', page: 1 })
  const query = useMyApplications({
    status: status as ApplicationStatus | '',
    sort: sort as ApplicationSort,
    page,
    pageSize: PAGE_SIZE,
  })
  const withdraw = useWithdrawApplication()
  const [target, setTarget] = useState<ApplicationListItem | null>(null)
  const [comment, setComment] = useState('')
  const [error, setError] = useState<string | null>(null)

  const close = () => {
    setTarget(null)
    setComment('')
    setError(null)
  }
  const confirm = async () => {
    if (!target) return
    setError(null)
    try {
      await withdraw.mutateAsync({ id: target.id, comment: comment.trim() || undefined })
      toast.success('Application withdrawn', { description: `${target.job_title} · ${target.company_name}` })
      close()
    } catch (e) {
      setError(withdrawMessage(e))
    }
  }

  const filtered = status !== ''

  return (
    <>
      <PageHeader
        title="My applications"
        description="Follow every application, see how it has progressed and withdraw while it is still in screening."
        actions={
          <Button asChild variant="outline">
            <Link to={paths.jobs}>Browse jobs</Link>
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="grid w-full gap-1.5 sm:w-52">
          <label htmlFor="app-status" className="text-sm font-medium">
            Status
          </label>
          <SimpleSelect
            id="app-status"
            value={status}
            onValueChange={(v) => update({ status: v })}
            options={STATUS_OPTIONS}
            emptyLabel="All statuses"
            placeholder="All statuses"
          />
        </div>
        <div className="grid w-full gap-1.5 sm:w-52">
          <label htmlFor="app-sort" className="text-sm font-medium">
            Sort by
          </label>
          <SimpleSelect
            id="app-sort"
            value={sort}
            onValueChange={(v) => update({ sort: v || 'newest' })}
            options={SORT_OPTIONS}
          />
        </div>
        {filtered && (
          <Button variant="ghost" onClick={() => update({ status: '' })}>
            Clear filter
          </Button>
        )}
        {query.data && (
          <p className="ml-auto text-sm text-muted-foreground" aria-live="polite">
            {query.data.total} application{query.data.total === 1 ? '' : 's'}
          </p>
        )}
      </div>

      {query.isPending ? (
        <ListSkeleton />
      ) : query.isError ? (
        <ErrorState
          error={query.error}
          onRetry={() => query.refetch()}
          title="Couldn't load your applications"
        />
      ) : query.data.items.length === 0 ? (
        <div className="rounded-xl border border-dashed">
          {filtered ? (
            <NoResults
              title="No applications with this status"
              description="Try another status or clear the filter."
              action={
                <Button variant="outline" onClick={() => update({ status: '' })}>
                  Show all applications
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={<BriefcaseBusiness aria-hidden />}
              title="You haven't applied to any jobs yet"
              description="Find a role that fits and apply in a couple of clicks — your progress will show up here."
              action={
                <>
                  <Button asChild>
                    <Link to={paths.jobs}>Browse jobs</Link>
                  </Button>
                  <Button asChild variant="outline">
                    <Link to={paths.recommended}>See recommendations</Link>
                  </Button>
                </>
              }
            />
          )}
        </div>
      ) : (
        <div className={cn(query.isFetching && 'opacity-70 transition-opacity')} aria-busy={query.isFetching}>
          <ul className="grid gap-3" aria-label="Applications">
            {query.data.items.map((a) => (
              <ApplicationCard key={a.id} application={a} onWithdraw={setTarget} />
            ))}
          </ul>
          <Pagination
            page={query.data.page}
            pages={query.data.pages}
            total={query.data.total}
            pageSize={query.data.page_size}
            onPageChange={(p) => update({ page: p }, { resetPage: false })}
            label="applications"
          />
        </div>
      )}

      <ConfirmDialog
        open={target !== null}
        onOpenChange={(o) => !o && close()}
        title="Withdraw this application?"
        description={
          <>
            Your application for <span className="font-medium">{target?.job_title}</span> at{' '}
            {target?.company_name} will be withdrawn and the hiring team will be notified. This can't be
            undone — you would need to apply again.
          </>
        }
        confirmLabel="Withdraw application"
        destructive
        loading={withdraw.isPending}
        onConfirm={confirm}
      >
        <Field
          label="Reason"
          optional
          hint="Shared with the hiring team. Plain text."
          error={
            comment.length > MAX_COMMENT
              ? `Keep it under ${MAX_COMMENT.toLocaleString()} characters`
              : undefined
          }
        >
          <Textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </ConfirmDialog>
    </>
  )
}
