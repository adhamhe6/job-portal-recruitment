import { ExternalLink, MapPin, Power, PowerOff, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ErrorState, Spinner } from '@/components/common/States'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { CompanyLogo } from '@/features/jobs/components/CompanyLogo'
import { useManagedJobs } from '@/features/jobs/api/jobs'
import { useCompanyMembers } from '@/features/companies/api/companies'
import { ROLE_LABELS } from '@/lib/enums'
import { dates, fmt } from '@/lib/format'
import { pluralize } from '@/lib/utils'
import { paths } from '@/routes/paths'
import type { AdminCompany } from '../api/types'
import { AccountStatusBadge } from './StatusPills'

/** Slide-over with a company's profile, member count / roster and recent jobs (all real endpoints). */
export function CompanyDetailsSheet({
  company,
  onOpenChange,
  onToggleStatus,
}: {
  company: AdminCompany | null
  onOpenChange: (open: boolean) => void
  onToggleStatus: (c: AdminCompany) => void
}) {
  return (
    <Sheet open={company !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="sm:w-[min(32rem,100vw)]">
        {company && <Details company={company} onToggleStatus={onToggleStatus} />}
      </SheetContent>
    </Sheet>
  )
}

function Details({
  company,
  onToggleStatus,
}: {
  company: AdminCompany
  onToggleStatus: (c: AdminCompany) => void
}) {
  const members = useCompanyMembers(company.id)
  const jobs = useManagedJobs({
    q: '',
    status: 'ALL',
    sort: 'newest',
    page: 1,
    pageSize: 5,
    companyId: company.id,
  })
  const suspended = company.status === 'SUSPENDED'

  return (
    <>
      <SheetHeader>
        <div className="flex items-center gap-3">
          <CompanyLogo name={company.name} logoUrl={company.logo_url} size="lg" />
          <div className="min-w-0">
            <SheetTitle className="truncate">{company.name}</SheetTitle>
            <SheetDescription className="flex flex-wrap items-center gap-2">
              <AccountStatusBadge status={company.status} />
              <span>Since {dates.date(company.created_at)}</span>
            </SheetDescription>
          </div>
        </div>
      </SheetHeader>
      <SheetBody className="space-y-6">
        {suspended && (
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
            This company is suspended. Its jobs are hidden from candidates and it cannot publish new jobs
            until it is reactivated.
          </p>
        )}
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
          {company.industry && (
            <>
              <dt className="text-muted-foreground">Industry</dt>
              <dd>{company.industry}</dd>
            </>
          )}
          {company.size && (
            <>
              <dt className="text-muted-foreground">Size</dt>
              <dd>{company.size} employees</dd>
            </>
          )}
          {company.location && (
            <>
              <dt className="text-muted-foreground">Location</dt>
              <dd className="flex items-center gap-1">
                <MapPin className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                {company.location}
              </dd>
            </>
          )}
          {company.website && (
            <>
              <dt className="text-muted-foreground">Website</dt>
              <dd className="min-w-0">
                <a
                  href={company.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex max-w-full items-center gap-1 text-primary hover:underline"
                >
                  <span className="truncate">{company.website.replace(/^https?:\/\//, '')}</span>
                  <ExternalLink className="size-3.5 shrink-0" aria-hidden />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              </dd>
            </>
          )}
          <dt className="text-muted-foreground">Slug</dt>
          <dd className="break-all font-mono text-xs">{company.slug}</dd>
        </dl>
        {company.description && (
          <p className="text-sm whitespace-pre-line text-muted-foreground">{company.description}</p>
        )}

        <section aria-labelledby="co-members" className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 id="co-members" className="text-sm font-semibold">
              Team members{members.data ? ` (${members.data.length})` : ''}
            </h3>
            <Button asChild variant="link" size="sm">
              <Link to={`${paths.adminUsers}?company=${company.id}`}>
                <Users /> View in Users
              </Link>
            </Button>
          </div>
          {members.isPending ? (
            <Spinner label="Loading members" className="py-4" />
          ) : members.isError ? (
            <ErrorState error={members.error} onRetry={() => members.refetch()} compact />
          ) : members.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">No staff accounts belong to this company yet.</p>
          ) : (
            <ul className="divide-y rounded-lg border">
              {members.data.map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">
                      {m.first_name} {m.last_name}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">{m.email}</span>
                  </span>
                  <span className="flex shrink-0 flex-wrap justify-end gap-1.5">
                    <Badge variant="outline">{ROLE_LABELS[m.role]}</Badge>
                    {m.is_company_admin && <Badge variant="violet">Company admin</Badge>}
                    {m.status !== 'ACTIVE' && <AccountStatusBadge status={m.status} />}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="co-jobs" className="space-y-2">
          <h3 id="co-jobs" className="text-sm font-semibold">
            Jobs{jobs.data ? ` (${fmt.int(jobs.data.total)})` : ''}
          </h3>
          {jobs.isPending ? (
            <div className="space-y-2" role="status" aria-label="Loading jobs">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : jobs.isError ? (
            <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} compact />
          ) : jobs.data.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">This company has not created any jobs.</p>
          ) : (
            <>
              <ul className="divide-y rounded-lg border">
                {jobs.data.items.map((j) => (
                  <li key={j.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                    <Link to={paths.job(j.id)} className="min-w-0 truncate font-medium hover:underline">
                      {j.title}
                    </Link>
                    <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                      {j.application_count !== null && j.application_count !== undefined && (
                        <span>{pluralize(j.application_count, 'application')}</span>
                      )}
                      <StatusBadge kind="job" status={j.status} />
                    </span>
                  </li>
                ))}
              </ul>
              {jobs.data.total > jobs.data.items.length && (
                <p className="text-xs text-muted-foreground">
                  Showing the newest {jobs.data.items.length} of {fmt.int(jobs.data.total)} jobs.
                </p>
              )}
            </>
          )}
        </section>

        <div className="border-t pt-4">
          <Button
            variant={suspended ? 'default' : 'destructive'}
            onClick={() => onToggleStatus(company)}
            className="w-full sm:w-auto"
          >
            {suspended ? <Power /> : <PowerOff />}
            {suspended ? 'Reactivate company' : 'Suspend company'}
          </Button>
        </div>
      </SheetBody>
    </>
  )
}
