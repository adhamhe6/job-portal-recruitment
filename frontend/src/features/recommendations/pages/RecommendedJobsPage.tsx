import { RefreshCw, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import { DebouncedInput } from '@/components/common/DebouncedInput'
import { FilterBar, type ActiveFilter } from '@/components/common/FilterBar'
import { PageHeader } from '@/components/common/PageHeader'
import { EmptyState, ErrorState, NoResults } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { MultiSelect } from '@/components/ui/combobox'
import { Field } from '@/components/ui/field'
import { Pagination } from '@/components/ui/pagination'
import { SimpleSelect } from '@/components/ui/select'
import { JobCardSkeleton } from '@/features/jobs/components/JobCard'
import { SkillTagInput } from '@/features/skills/components/SkillPicker'
import { isTaskDone, useTask } from '@/features/tasks/api/tasks'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { ApiError, errorMessage } from '@/lib/api'
import {
  EMPLOYMENT_TYPE_LABELS,
  EMPLOYMENT_TYPE_OPTIONS,
  WORKPLACE_TYPE_LABELS,
  WORKPLACE_TYPE_OPTIONS,
} from '@/lib/enums'
import { dates } from '@/lib/format'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { recommendationKeys, useRecommendations, useRefreshRecommendations } from '../api/recommendations'
import { RecommendationCard } from '../components/RecommendationCard'
import { RefreshStatus } from '../components/RefreshStatus'
import {
  asEmployment,
  asWorkplace,
  decodeSkill,
  encodeSkill,
  MIN_SCORE_OPTIONS,
  SORT_OPTIONS,
} from '../lib/filters'

const DEFAULTS = {
  minScore: '',
  workplace: [] as string[],
  employment: [] as string[],
  location: '',
  skill: [] as string[],
  sort: 'score',
  page: 1,
}

function refreshErrorMessage(e: unknown): string {
  if (e instanceof ApiError && e.status === 429)
    return 'You refreshed recently. Please wait a minute before trying again.'
  return errorMessage(e)
}

export default function RecommendedJobsPage() {
  useDocumentTitle('Recommended jobs')
  const qc = useQueryClient()
  const [state, update, reset] = useUrlState(DEFAULTS)
  const skills = state.skill.map(decodeSkill).filter((s): s is NonNullable<typeof s> => s !== null)

  const query = useRecommendations({
    minScore: Number(state.minScore) || 0,
    workplace: asWorkplace(state.workplace),
    employment: asEmployment(state.employment),
    location: state.location,
    skillIds: skills.map((s) => s.id ?? ''),
    sort: state.sort === 'newest' ? 'newest' : 'score',
    page: state.page,
  })

  // --- background refresh ---------------------------------------------------------------------------------------
  const refresh = useRefreshRecommendations()
  const [startedTask, setStartedTask] = useState<string | null>(null)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const meta = query.data?.meta
  const taskId = startedTask ?? (meta?.computing ? (meta.task_id ?? null) : null)
  const task = useTask(taskId)
  const taskStatus = task.data?.status
  const running = refresh.isPending || (Boolean(taskId) && !isTaskDone(task.data))

  useEffect(() => {
    if (!taskId || !taskStatus) return
    if (taskStatus === 'COMPLETED') {
      void qc.invalidateQueries({ queryKey: recommendationKeys.all })
      toast.success('Recommendations refreshed')
    }
  }, [taskId, taskStatus, qc])

  const startRefresh = async () => {
    setRefreshError(null)
    try {
      const ref = await refresh.mutateAsync()
      setStartedTask(ref.task_id)
    } catch (e) {
      setRefreshError(refreshErrorMessage(e))
    }
  }

  // --- filters ---------------------------------------------------------------------------------------------------
  const active: ActiveFilter[] = [
    ...(state.minScore
      ? [
          {
            key: 'min',
            label: `Match ${state.minScore}%+`,
            onRemove: () => update({ minScore: '' }),
          },
        ]
      : []),
    ...state.workplace.map((w) => ({
      key: `w-${w}`,
      label: WORKPLACE_TYPE_LABELS[w as keyof typeof WORKPLACE_TYPE_LABELS] ?? w,
      onRemove: () => update({ workplace: state.workplace.filter((x) => x !== w) }),
    })),
    ...state.employment.map((e) => ({
      key: `e-${e}`,
      label: EMPLOYMENT_TYPE_LABELS[e as keyof typeof EMPLOYMENT_TYPE_LABELS] ?? e,
      onRemove: () => update({ employment: state.employment.filter((x) => x !== e) }),
    })),
    ...(state.location
      ? [{ key: 'loc', label: `Location: ${state.location}`, onRemove: () => update({ location: '' }) }]
      : []),
    ...skills.map((s) => ({
      key: `s-${s.id}`,
      label: `Skill: ${s.name}`,
      onRemove: () => update({ skill: state.skill.filter((x) => decodeSkill(x)?.id !== s.id) }),
    })),
  ]
  const filtered = active.length > 0

  return (
    <>
      <PageHeader
        title="Recommended jobs"
        description="Open roles ranked by how well your skills, experience and preferences fit — with the reasons."
        meta={
          meta?.last_generated_at ? (
            <span className="text-xs text-muted-foreground">
              Last updated {dates.relative(meta.last_generated_at)}
            </span>
          ) : undefined
        }
        actions={
          <Button variant="outline" onClick={startRefresh} loading={running} disabled={running}>
            <RefreshCw /> Refresh recommendations
          </Button>
        }
      />

      <RefreshStatus
        task={task.data}
        queued={refresh.isPending || (Boolean(taskId) && task.isPending)}
        error={refreshError}
      />

      {meta && !meta.profile_ready && (
        <Alert
          variant="warning"
          title="Complete your profile for better recommendations"
          className="mb-4"
          action={
            <Button asChild size="sm" variant="outline">
              <Link to={paths.profile}>Update profile</Link>
            </Button>
          }
        >
          {meta.hint ?? 'Add skills, experience or upload a résumé so we can match you with jobs.'}
        </Alert>
      )}

      <FilterBar
        className="mb-5"
        active={active}
        onClearAll={() => reset(['minScore', 'workplace', 'employment', 'location', 'skill'])}
        trailing={
          <div className="w-44">
            <SimpleSelect
              aria-label="Sort recommendations"
              value={state.sort}
              onValueChange={(v) => update({ sort: v || 'score' })}
              options={SORT_OPTIONS}
            />
          </div>
        }
      >
        <div className="grid w-full gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Minimum match">
            <SimpleSelect
              value={state.minScore}
              onValueChange={(v) => update({ minScore: v })}
              options={MIN_SCORE_OPTIONS}
              emptyLabel="Any match"
              placeholder="Any match"
            />
          </Field>
          <Field label="Workplace" htmlFor="rec-workplace">
            <MultiSelect
              id="rec-workplace"
              values={state.workplace}
              onChange={(v) => update({ workplace: v })}
              options={WORKPLACE_TYPE_OPTIONS}
              placeholder="Any workplace"
              showChips={false}
            />
          </Field>
          <Field label="Employment type" htmlFor="rec-employment">
            <MultiSelect
              id="rec-employment"
              values={state.employment}
              onChange={(v) => update({ employment: v })}
              options={EMPLOYMENT_TYPE_OPTIONS}
              placeholder="Any type"
              showChips={false}
            />
          </Field>
          <Field label="Location">
            <DebouncedInput
              value={state.location}
              onValueChange={(v) => update({ location: v })}
              placeholder="City or country"
              maxLength={100}
            />
          </Field>
          <Field label="Skills" htmlFor="rec-skills" className="sm:col-span-2">
            <SkillTagInput
              id="rec-skills"
              value={skills}
              onChange={(next) => update({ skill: next.filter((s) => s.id).map(encodeSkill) })}
              placeholder="Only jobs requiring…"
              chipsLabel="Skill filters"
            />
          </Field>
        </div>
      </FilterBar>

      {query.isPending ? (
        <div className="space-y-3" role="status" aria-busy="true" aria-label="Loading recommendations">
          {[0, 1, 2, 3].map((i) => (
            <JobCardSkeleton key={i} />
          ))}
        </div>
      ) : query.isError && !query.data ? (
        <ErrorState
          error={query.error}
          onRetry={() => query.refetch()}
          title="We couldn't load your recommendations"
        />
      ) : query.data && query.data.items.length === 0 ? (
        <div className="rounded-xl border border-dashed">
          {filtered ? (
            <NoResults
              title="No recommendations match these filters"
              description="Loosen the minimum match or remove a filter to see more roles."
              action={
                <Button
                  variant="outline"
                  onClick={() => reset(['minScore', 'workplace', 'employment', 'location', 'skill'])}
                >
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={<Sparkles aria-hidden />}
              title={meta?.computing ? 'Working on your recommendations' : 'No recommendations yet'}
              description={
                meta?.computing
                  ? 'This takes a moment. The list will appear here when it is ready.'
                  : (meta?.hint ??
                    'Add skills to your profile or upload a résumé, then refresh to get ranked suggestions.')
              }
              action={
                <>
                  <Button asChild>
                    <Link to={paths.profile}>Complete profile</Link>
                  </Button>
                  <Button asChild variant="outline">
                    <Link to={paths.resume}>Upload résumé</Link>
                  </Button>
                </>
              }
            />
          )}
        </div>
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
          <p className="mb-3 text-sm text-muted-foreground" aria-live="polite">
            {query.data.total} job{query.data.total === 1 ? '' : 's'} recommended
          </p>
          <ul
            className={cn('space-y-4 transition-opacity', query.isPlaceholderData && 'opacity-60')}
            aria-label="Recommended jobs"
            aria-busy={query.isPlaceholderData || undefined}
          >
            {query.data.items.map((item) => (
              <RecommendationCard key={item.job.id} item={item} />
            ))}
          </ul>
          <Pagination
            page={query.data.page}
            pages={query.data.pages}
            total={query.data.total}
            pageSize={query.data.page_size}
            onPageChange={(p) => update({ page: p }, { resetPage: false })}
            label="recommendations"
            className="mt-4"
          />
        </div>
      ) : null}
    </>
  )
}
