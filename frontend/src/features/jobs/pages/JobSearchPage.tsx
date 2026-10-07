import { SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { SearchInput } from '@/components/common/SearchInput'
import { FilterBar, type ActiveFilter } from '@/components/common/FilterBar'
import { NoResults } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/input'
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useCompany } from '@/features/companies/api/companies'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { useUrlState } from '@/hooks/useUrlState'
import { EMPLOYMENT_TYPE_LABELS, EXPERIENCE_LEVEL_LABELS, JOB_SORT_LABELS, POSTED_WITHIN_OPTIONS, WORKPLACE_TYPE_LABELS } from '@/lib/enums'
import { fmt } from '@/lib/format'
import type { EmploymentType, ExperienceLevel, JobSort, WorkplaceType } from '@/lib/api'
import { paths } from '@/routes/paths'
import { useJobSearch } from '../api/jobs'
import { JobFilters } from '../components/JobFilters'
import { JobResults } from '../components/JobResults'
import { JobsTabs } from '../components/JobsTabs'
import { countActiveFilters, JOB_SEARCH_DEFAULTS, type JobSearchState } from '../lib/filters'

const labelOf = <T extends string>(map: Record<T, string>, key: string) => map[key as T] ?? key

function activeFilterChips(state: JobSearchState, update: (p: Partial<JobSearchState>) => void, companyName: string | null | undefined): ActiveFilter[] {
  const without = (list: string[], v: string) => list.filter((x) => x !== v)
  const chips: ActiveFilter[] = []
  state.skill.forEach((s) => chips.push({ key: `skill:${s}`, label: s, onRemove: () => update({ skill: without(state.skill, s) }) }))
  if (state.location.trim()) chips.push({ key: 'location', label: `Location: ${state.location}`, onRemove: () => update({ location: '' }) })
  state.workplace_type.forEach((v) => chips.push({ key: `wp:${v}`, label: labelOf<WorkplaceType>(WORKPLACE_TYPE_LABELS, v), onRemove: () => update({ workplace_type: without(state.workplace_type, v) }) }))
  state.employment_type.forEach((v) => chips.push({ key: `et:${v}`, label: labelOf<EmploymentType>(EMPLOYMENT_TYPE_LABELS, v), onRemove: () => update({ employment_type: without(state.employment_type, v) }) }))
  state.experience_level.forEach((v) => chips.push({ key: `lv:${v}`, label: labelOf<ExperienceLevel>(EXPERIENCE_LEVEL_LABELS, v), onRemove: () => update({ experience_level: without(state.experience_level, v) }) }))
  if (state.max_experience) chips.push({ key: 'maxexp', label: `≤ ${state.max_experience} yrs experience`, onRemove: () => update({ max_experience: '' }) })
  if (state.salary_min || state.salary_max) {
    const lo = state.salary_min ? fmt.int(state.salary_min) : '0'
    const hi = state.salary_max ? fmt.int(state.salary_max) : '∞'
    chips.push({ key: 'salary', label: `Salary ${lo} – ${hi}`, onRemove: () => update({ salary_min: '', salary_max: '' }) })
  }
  if (state.posted_within_days) {
    const o = POSTED_WITHIN_OPTIONS.find((x) => x.value === state.posted_within_days)
    chips.push({ key: 'posted', label: o?.label ?? `Last ${state.posted_within_days} days`, onRemove: () => update({ posted_within_days: '' }) })
  }
  if (state.company_id) chips.push({ key: 'company', label: companyName ?? 'Selected company', onRemove: () => update({ company_id: '' }) })
  return chips
}

export default function JobSearchPage() {
  useDocumentTitle('Find jobs')
  const { isCandidate } = useAuth()
  const isDesktop = useMediaQuery('(min-width: 1024px)', true)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [state, update, reset] = useUrlState(JOB_SEARCH_DEFAULTS)
  const query = useJobSearch(state)
  const company = useCompany(state.company_id || undefined)
  const companyName = company.data?.name

  const active = countActiveFilters(state)
  const hasAnything = active > 0 || state.q.trim() !== ''
  const total = query.data?.total
  const clearFilters = () => reset(['skill', 'skills_mode', 'location', 'employment_type', 'workplace_type', 'experience_level', 'max_experience', 'salary_min', 'salary_max', 'posted_within_days', 'company_id', 'page'])
  const clearAll = () => reset()

  const sortValue = !state.q.trim() && state.sort === 'relevance' ? 'newest' : state.sort
  const sortOptions: JobSort[] = [...(state.q.trim() ? (['relevance'] as JobSort[]) : []), 'newest', 'salary_desc', 'salary_asc', 'deadline', ...(isCandidate ? (['match'] as JobSort[]) : [])]

  const filters = (
    <JobFilters state={state} update={(p) => update(p)} onClear={clearFilters} companyName={companyName} />
  )

  return (
    <>
      <PageHeader title="Find jobs" description="Search open roles. Share the link to share your exact filters." />
      <JobsTabs />

      <div className="grid items-start gap-6 lg:grid-cols-[17.5rem_minmax(0,1fr)]">
        {isDesktop && (
          <aside aria-label="Filters" className="sticky top-24 max-h-[calc(100dvh-7rem)] overflow-y-auto rounded-xl border bg-card p-5">
            {filters}
          </aside>
        )}

        <div className="min-w-0 space-y-4">
          <FilterBar
            active={activeFilterChips(state, (p) => update(p), companyName)}
            onClearAll={clearFilters}
            trailing={
              <div className="flex items-center gap-2">
                <label htmlFor="job-sort" className="sr-only sm:not-sr-only sm:text-sm sm:text-muted-foreground">
                  Sort by
                </label>
                <NativeSelect id="job-sort" className="w-44" value={sortValue} onChange={(e) => update({ sort: e.target.value })}>
                  {sortOptions.map((s) => (
                    <option key={s} value={s}>
                      {JOB_SORT_LABELS[s]}
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
              placeholder="Search by title, skill or keyword"
              label="Search jobs"
            />
            {!isDesktop && (
              <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
                <SheetTrigger asChild>
                  <Button variant="outline">
                    <SlidersHorizontal /> Filters{active > 0 && <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground tabular">{active}</span>}
                  </Button>
                </SheetTrigger>
                <SheetContent side="right" aria-describedby="filters-desc" className="w-[min(24rem,100vw)] gap-0">
                  <SheetHeader>
                    <SheetTitle>Filters</SheetTitle>
                    <SheetDescription id="filters-desc">Results update as you change filters.</SheetDescription>
                  </SheetHeader>
                  <SheetBody className="py-5">{filters}</SheetBody>
                  <SheetFooter>
                    <Button variant="outline" className="flex-1" onClick={clearFilters} disabled={active === 0}>
                      Clear
                    </Button>
                    <Button className="flex-[2]" onClick={() => setSheetOpen(false)}>
                      Show {total !== undefined ? fmt.int(total) : ''} jobs
                    </Button>
                  </SheetFooter>
                </SheetContent>
              </Sheet>
            )}
          </FilterBar>

          <p className="text-sm text-muted-foreground" aria-live="polite" role="status">
            {query.isPending ? 'Searching…' : total !== undefined ? `${fmt.int(total)} ${total === 1 ? 'job' : 'jobs'} found` : ''}
          </p>

          <JobResults
            query={query}
            highlightSkills={state.skill}
            onPageChange={(page) => {
              update({ page }, { resetPage: false })
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }}
            empty={
              <NoResults
                title="No jobs found"
                description="Try changing your filters."
                action={
                  hasAnything ? (
                    <Button variant="outline" onClick={clearAll}>
                      Clear filters
                    </Button>
                  ) : (
                    <Button asChild variant="outline">
                      <Link to={paths.home}>Back to home</Link>
                    </Button>
                  )
                }
              />
            }
          />
        </div>
      </div>
    </>
  )
}
