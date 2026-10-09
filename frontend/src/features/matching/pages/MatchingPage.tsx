import { SlidersHorizontal } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { SearchInput } from '@/components/common/SearchInput'
import { StatusBadge } from '@/components/common/StatusBadge'
import { EmptyState, ErrorState, NoResults } from '@/components/common/States'
import { ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { useJob, useManagedJobs, isStaffView } from '@/features/jobs/api/jobs'
import { useRankedCandidates } from '@/features/matches/api/matches'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { cn, pluralize } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { JobMatchCard, JobMatchCardSkeleton } from '../components/JobMatchCard'
import { MatchingFilters } from '../components/MatchingFilters'
import { RankedCandidateCard, RankedCandidateSkeleton } from '../components/RankedCandidateCard'
import { RefreshMatchesPanel } from '../components/RefreshMatchesPanel'
import { ScoreDisclaimer } from '../components/ScoreDisclaimer'
import { countActiveFilters, MATCHING_DEFAULTS, toRankedFilters } from '../lib/matching'

const JOB_PAGE_SIZE = 12
const STATUS_OPTIONS = [
  { value: 'PUBLISHED', label: 'Published' },
  { value: 'PAUSED', label: 'Paused' },
  { value: 'DRAFT', label: 'Drafts' },
  { value: 'CLOSED', label: 'Closed' },
  { value: 'ALL', label: 'All statuses' },
] as const

/** /matching: choose one of your company's jobs, each with its match summary. */
function JobPicker() {
  useDocumentTitle('Candidate matching')
  const [state, update, reset] = useUrlState({ q: '', status: 'PUBLISHED', page: 1 })
  const status = STATUS_OPTIONS.some((o) => o.value === state.status) ? state.status : 'PUBLISHED'
  const jobs = useManagedJobs({
    q: state.q,
    status,
    sort: 'newest',
    page: state.page,
    pageSize: JOB_PAGE_SIZE,
  })
  const hasFilters = Boolean(state.q.trim()) || status !== 'PUBLISHED'

  return (
    <>
      <PageHeader
        title="Candidate matching"
        description="Pick a job to see candidates ranked by how well they fit it, with an explanation for every score."
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SearchInput
          className="min-w-0 flex-1 basis-60"
          value={state.q}
          onChange={(q) => update({ q })}
          placeholder="Search your jobs"
          label="Search jobs"
        />
        <label htmlFor="matching-status" className="sr-only">
          Job status
        </label>
        <NativeSelect
          id="matching-status"
          className="w-44"
          value={status}
          onChange={(e) => update({ status: e.target.value })}
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </div>
      <ScoreDisclaimer className="mb-4" />

      {jobs.isPending ? (
        <div
          className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
          role="status"
          aria-busy="true"
          aria-label="Loading jobs"
        >
          {Array.from({ length: 6 }).map((_, i) => (
            <JobMatchCardSkeleton key={i} />
          ))}
        </div>
      ) : jobs.isError && !jobs.data ? (
        <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} title="We couldn't load your jobs" />
      ) : jobs.data && jobs.data.items.length === 0 ? (
        hasFilters ? (
          <NoResults
            title="No jobs match"
            description="Try another status or search."
            action={
              <Button variant="outline" onClick={() => reset()}>
                Clear filters
              </Button>
            }
          />
        ) : (
          <EmptyState
            title="No published jobs yet"
            description="Candidates are matched against your jobs. Publish a job to get a ranked list of candidates."
            action={
              <Button asChild>
                <Link to={paths.manageJobs}>Manage jobs</Link>
              </Button>
            }
          />
        )
      ) : jobs.data ? (
        <div>
          <ul
            className={cn('grid gap-4 sm:grid-cols-2 xl:grid-cols-3', jobs.isPlaceholderData && 'opacity-60')}
            aria-label="Jobs"
          >
            {jobs.data.items.map((job) => (
              <li key={job.id}>
                <JobMatchCard job={job} />
              </li>
            ))}
          </ul>
          <Pagination
            page={jobs.data.page}
            pages={jobs.data.pages}
            total={jobs.data.total}
            pageSize={jobs.data.page_size}
            onPageChange={(page) => update({ page }, { resetPage: false })}
            label="jobs"
            className="mt-4"
          />
        </div>
      ) : null}
    </>
  )
}

/** /matching/:jobId: ranked candidates for one job. */
function JobRanking({ jobId }: { jobId: string }) {
  const [state, update, reset] = useUrlState(MATCHING_DEFAULTS)
  const job = useJob(jobId)
  const ranked = useRankedCandidates(jobId, toRankedFilters(state))
  const jobTitle = job.data?.title
  useDocumentTitle(jobTitle ? `Matching · ${jobTitle}` : 'Candidate matching')

  const active = countActiveFilters(state)
  const data = ranked.data
  const meta = data?.meta
  const pageOffset = data ? (data.page - 1) * data.page_size : 0
  const total = data?.total

  // A job we cannot read (404 foreign/unknown id, 403) makes the whole page meaningless.
  const blocking = [job.error, ranked.error].find(
    (e): e is ApiError => e instanceof ApiError && (e.status === 403 || e.status === 404),
  )

  const header = (
    <PageHeader
      breadcrumbs={[{ label: 'Matching', to: paths.matching }, { label: jobTitle ?? 'Job' }]}
      title={jobTitle ? `Candidates for ${jobTitle}` : 'Candidate matching'}
      description="Candidates ranked by how well their profile fits this job."
      meta={
        job.data && isStaffView(job.data) ? <StatusBadge kind="job" status={job.data.status} /> : undefined
      }
      actions={
        <>
          <Button asChild variant="outline">
            <Link to={`${paths.applications}?job_id=${jobId}`}>Applications</Link>
          </Button>
          <Button asChild variant="outline">
            <Link to={paths.matching}>Change job</Link>
          </Button>
        </>
      }
    />
  )

  if (blocking)
    return (
      <>
        <PageHeader
          breadcrumbs={[{ label: 'Matching', to: paths.matching }, { label: 'Job' }]}
          title="Candidate matching"
        />
        <ErrorState
          error={blocking}
          onRetry={() => {
            void job.refetch()
            void ranked.refetch()
          }}
          title={blocking.status === 403 ? 'Access denied' : 'Job not found'}
        />
        <div className="flex justify-center">
          <Button asChild variant="outline">
            <Link to={paths.matching}>Back to your jobs</Link>
          </Button>
        </div>
      </>
    )

  return (
    <>
      {header}
      <div className="space-y-4">
        <RefreshMatchesPanel jobId={jobId} meta={meta} />
        <ScoreDisclaimer />
        <MatchingFilters state={state} update={(p) => update(p)} onClear={() => reset()} />

        <p className="text-sm text-muted-foreground" role="status" aria-live="polite">
          {ranked.isPending
            ? 'Loading ranking…'
            : total !== undefined
              ? `${pluralize(total, 'candidate')} ${active > 0 ? 'match your filters' : 'ranked'}`
              : ''}
        </p>

        {ranked.isPending ? (
          <div className="space-y-3" role="status" aria-busy="true" aria-label="Loading ranked candidates">
            {Array.from({ length: 4 }).map((_, i) => (
              <RankedCandidateSkeleton key={i} />
            ))}
          </div>
        ) : ranked.isError && !data ? (
          <ErrorState
            error={ranked.error}
            onRetry={() => ranked.refetch()}
            title="We couldn't load the ranking"
          />
        ) : data && data.items.length === 0 ? (
          active > 0 ? (
            <NoResults
              title="No candidates match these filters"
              description="Lower the minimum score or remove a filter to see more candidates."
              action={
                <Button variant="outline" onClick={() => reset()}>
                  <SlidersHorizontal /> Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              title="No candidates scored yet"
              description={
                meta?.computing_task_id
                  ? 'Matches are being calculated. They will appear here when the refresh finishes.'
                  : 'Use “Refresh matches” to score the candidates visible to your company against this job.'
              }
            />
          )
        ) : data ? (
          <div>
            {ranked.isError && (
              <ErrorState
                compact
                error={ranked.error}
                onRetry={() => ranked.refetch()}
                title="Showing earlier results"
              />
            )}
            <ol
              aria-label="Ranked candidates"
              className={cn('space-y-3 transition-opacity', ranked.isPlaceholderData && 'opacity-60')}
              aria-busy={ranked.isPlaceholderData || undefined}
            >
              {data.items.map((m, i) => (
                <li key={m.candidate_id}>
                  <RankedCandidateCard match={m} jobId={jobId} rank={pageOffset + i + 1} />
                </li>
              ))}
            </ol>
            <Pagination
              page={data.page}
              pages={data.pages}
              total={data.total}
              pageSize={data.page_size}
              onPageChange={(page) => {
                update({ page }, { resetPage: false })
                window.scrollTo({ top: 0, behavior: 'smooth' })
              }}
              label="candidates"
              className="mt-4"
            />
          </div>
        ) : null}
      </div>
    </>
  )
}

export default function MatchingPage() {
  const { jobId } = useParams()
  return jobId ? <JobRanking jobId={jobId} /> : <JobPicker />
}
