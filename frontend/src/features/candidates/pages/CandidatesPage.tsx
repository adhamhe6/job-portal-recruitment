import { ShieldAlert, SlidersHorizontal, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { EmptyState, ErrorState, NoResults } from '@/components/common/States'
import { FilterBar, type ActiveFilter } from '@/components/common/FilterBar'
import { PageHeader } from '@/components/common/PageHeader'
import { SearchInput } from '@/components/common/SearchInput'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { useUrlState } from '@/hooks/useUrlState'
import { fmt } from '@/lib/format'
import { cn, pluralize } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { useCandidateSearch } from '../api/candidates'
import { BulkImportDialog } from '../components/BulkImportDialog'
import { CandidateCard, CandidateCardSkeleton } from '../components/CandidateCard'
import { CandidateFilters } from '../components/CandidateFilters'
import { useJobOptions } from '../hooks/useJobOptions'
import {
  AVAILABILITY_LABELS,
  CANDIDATE_SEARCH_DEFAULTS,
  CANDIDATE_SORT_LABELS,
  countActiveFilters,
  EDUCATION_LEVEL_OPTIONS,
  REMOTE_PREFERENCE_LABELS,
  type Availability,
  type CandidateSearchState,
  type CandidateSort,
  type RemotePreference,
} from '../lib/filters'

const SORTS: CandidateSort[] = ['relevance', 'match', 'experience', 'recent', 'name']

function activeChips(
  s: CandidateSearchState,
  update: (p: Partial<CandidateSearchState>) => void,
  jobTitle: string | undefined,
): ActiveFilter[] {
  const without = (list: string[], v: string) => list.filter((x) => x !== v)
  const chips: ActiveFilter[] = []
  s.skill.forEach((k) =>
    chips.push({ key: `skill:${k}`, label: k, onRemove: () => update({ skill: without(s.skill, k) }) }),
  )
  if (s.min_experience || s.max_experience) {
    const lo = s.min_experience || '0'
    const hi = s.max_experience || '∞'
    chips.push({
      key: 'exp',
      label: `${lo}–${hi} yrs experience`,
      onRemove: () => update({ min_experience: '', max_experience: '' }),
    })
  }
  if (s.location.trim())
    chips.push({ key: 'loc', label: `Location: ${s.location}`, onRemove: () => update({ location: '' }) })
  if (s.min_education) {
    const label = EDUCATION_LEVEL_OPTIONS.find((o) => o.value === s.min_education)?.label ?? s.min_education
    chips.push({ key: 'edu', label: `Education: ${label}+`, onRemove: () => update({ min_education: '' }) })
  }
  if (s.certification.trim())
    chips.push({
      key: 'cert',
      label: `Certification: ${s.certification}`,
      onRemove: () => update({ certification: '' }),
    })
  s.availability.forEach((v) =>
    chips.push({
      key: `av:${v}`,
      label: AVAILABILITY_LABELS[v as Availability] ?? v,
      onRemove: () => update({ availability: without(s.availability, v) }),
    }),
  )
  s.remote_preference.forEach((v) =>
    chips.push({
      key: `rp:${v}`,
      label: REMOTE_PREFERENCE_LABELS[v as RemotePreference] ?? v,
      onRemove: () => update({ remote_preference: without(s.remote_preference, v) }),
    }),
  )
  if (s.job_id)
    chips.push({
      key: 'job',
      label: `Matched to ${jobTitle ?? 'selected job'}`,
      onRemove: () => update({ job_id: '', min_match_score: '' }),
    })
  if (s.job_id && s.min_match_score)
    chips.push({
      key: 'minmatch',
      label: `Match ≥ ${s.min_match_score}%`,
      onRemove: () => update({ min_match_score: '' }),
    })
  if (s.applicants_only === 'true')
    chips.push({ key: 'appl', label: 'Applicants only', onRemove: () => update({ applicants_only: '' }) })
  return chips
}

export default function CandidatesPage() {
  useDocumentTitle('Candidates')
  const { can } = useAuth()
  const isDesktop = useMediaQuery('(min-width: 1024px)', true)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [state, update, reset] = useUrlState(CANDIDATE_SEARCH_DEFAULTS)
  const canSearch = can('search_candidates')
  const query = useCandidateSearch(state, canSearch)
  const jobs = useJobOptions()

  const active = countActiveFilters(state)
  const hasAnything = active > 0 || state.q.trim() !== ''
  const total = query.data?.total
  const jobTitle = jobs.options.find((o) => o.value === state.job_id)?.label
  const clearFilters = () =>
    reset([
      'skill',
      'skills_mode',
      'min_experience',
      'max_experience',
      'location',
      'min_education',
      'certification',
      'availability',
      'remote_preference',
      'job_id',
      'min_match_score',
      'applicants_only',
      'page',
    ])

  // Relevance only means something with a keyword; best-match only with a job. Show the effective sort.
  const hasKeyword = state.q.trim() !== ''
  const sortOptions = SORTS.filter((s) => (s === 'match' ? Boolean(state.job_id) : true))
  const sortValue = sortOptions.includes(state.sort as CandidateSort) ? state.sort : 'relevance'

  const filters = (
    <CandidateFilters state={state} update={(p) => update(p)} onClear={clearFilters} hideTitle={!isDesktop} />
  )

  if (!canSearch)
    return (
      <>
        <PageHeader title="Candidates" />
        <EmptyState
          icon={<ShieldAlert aria-hidden />}
          title="Candidate search isn’t available for your role"
          description="You can open a candidate from an application or from a job’s match ranking. Ask a recruiter if you need to search the whole talent pool."
          action={
            <Button asChild variant="outline">
              <Link to={paths.applications}>Go to applications</Link>
            </Button>
          }
        />
      </>
    )

  return (
    <>
      <PageHeader
        title="Candidates"
        description="Search candidates who applied to your jobs, opted in to the talent marketplace, or were imported by your company. Share the link to share your exact filters."
        actions={
          can('import_resumes') && (
            <Button variant="outline" onClick={() => setImportOpen(true)}>
              <Upload /> Bulk résumé import
            </Button>
          )
        }
      />
      {can('import_resumes') && <BulkImportDialog open={importOpen} onOpenChange={setImportOpen} />}

      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[19rem_minmax(0,1fr)]">
        {isDesktop && (
          <aside
            aria-label="Filters"
            className="sticky top-24 max-h-[calc(100dvh-7rem)] overflow-y-auto rounded-xl border bg-card p-5"
          >
            {filters}
          </aside>
        )}

        <div className="min-w-0 space-y-4">
          <FilterBar
            active={activeChips(state, (p) => update(p), jobTitle)}
            onClearAll={clearFilters}
            trailing={
              <div className="flex items-center gap-2">
                <label
                  htmlFor="candidate-sort"
                  className="sr-only sm:not-sr-only sm:text-sm sm:whitespace-nowrap sm:text-muted-foreground"
                >
                  Sort by
                </label>
                <NativeSelect
                  id="candidate-sort"
                  className="w-44"
                  value={sortValue}
                  onChange={(e) => update({ sort: e.target.value })}
                >
                  {sortOptions.map((s) => (
                    <option key={s} value={s}>
                      {CANDIDATE_SORT_LABELS[s]}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            }
          >
            <SearchInput
              className="min-w-0 flex-1 basis-60"
              value={state.q}
              onChange={(q) => update({ q })}
              placeholder="Search by name, title, skill or keyword"
              label="Search candidates"
            />
            {!isDesktop && (
              <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
                <SheetTrigger asChild>
                  <Button variant="outline">
                    <SlidersHorizontal /> Filters
                    {active > 0 && (
                      <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground tabular">
                        {active}
                      </span>
                    )}
                  </Button>
                </SheetTrigger>
                <SheetContent
                  side="right"
                  aria-describedby="cand-filters-desc"
                  className="w-[min(24rem,100vw)] gap-0"
                >
                  <SheetHeader>
                    <SheetTitle>Filters</SheetTitle>
                    <SheetDescription id="cand-filters-desc">
                      Results update as you change filters.
                    </SheetDescription>
                  </SheetHeader>
                  <SheetBody className="py-5">{filters}</SheetBody>
                  <SheetFooter>
                    <Button
                      variant="outline"
                      className="flex-1"
                      onClick={clearFilters}
                      disabled={active === 0}
                    >
                      Clear
                    </Button>
                    <Button className="flex-[2]" onClick={() => setSheetOpen(false)}>
                      Show {total !== undefined ? fmt.int(total) : ''} candidates
                    </Button>
                  </SheetFooter>
                </SheetContent>
              </Sheet>
            )}
          </FilterBar>

          <p className="text-sm text-muted-foreground" aria-live="polite" role="status">
            {query.isPending
              ? 'Searching…'
              : total !== undefined
                ? `${pluralize(total, 'candidate')} found${hasKeyword && state.sort === 'relevance' ? ' · sorted by relevance' : ''}`
                : ''}
          </p>

          {query.isPending ? (
            <div className="space-y-3" role="status" aria-busy="true" aria-label="Loading candidates">
              {Array.from({ length: 5 }).map((_, i) => (
                <CandidateCardSkeleton key={i} />
              ))}
            </div>
          ) : query.isError && !query.data ? (
            <ErrorState
              error={query.error}
              onRetry={() => query.refetch()}
              title="We couldn't search candidates"
            />
          ) : query.data && query.data.items.length === 0 ? (
            hasAnything ? (
              <NoResults
                title="No candidates found"
                description="Try fewer filters, a different spelling, or ‘Any of these’ for skills."
                action={
                  <Button variant="outline" onClick={() => reset()}>
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <EmptyState
                title="No candidates yet"
                description="You will see people here once they apply to your jobs, opt in to the talent marketplace, or you import résumés."
                action={
                  can('import_resumes') ? (
                    <Button onClick={() => setImportOpen(true)}>
                      <Upload /> Bulk résumé import
                    </Button>
                  ) : undefined
                }
              />
            )
          ) : query.data ? (
            <div>
              {query.isError && (
                <ErrorState
                  compact
                  error={query.error}
                  onRetry={() => query.refetch()}
                  title="Showing earlier results"
                />
              )}
              <ul
                aria-label="Candidates"
                className={cn('space-y-3 transition-opacity', query.isPlaceholderData && 'opacity-60')}
                aria-busy={query.isPlaceholderData || undefined}
              >
                {query.data.items.map((c) => (
                  <li key={c.id}>
                    <CandidateCard candidate={c} jobId={state.job_id || undefined} />
                  </li>
                ))}
              </ul>
              <Pagination
                page={query.data.page}
                pages={query.data.pages}
                total={query.data.total}
                pageSize={query.data.page_size}
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
      </div>
    </>
  )
}
