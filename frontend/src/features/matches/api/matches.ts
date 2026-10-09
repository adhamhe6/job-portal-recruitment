import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, type CandidateFacingMatch, type components } from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'

export const matchKeys = { myJob: (jobId: string) => ['matches', 'me', 'job', jobId] as const }

/**
 * "How you match" for the signed-in candidate. Resolves to `null` (not an error) when no match was computed
 * (404), so the UI can simply hide the card.
 */
export function useMyJobMatch(jobId: string | undefined) {
  const { isCandidate } = useAuth()
  return useQuery({
    queryKey: matchKeys.myJob(jobId ?? ''),
    enabled: Boolean(jobId) && isCandidate,
    queryFn: async ({ signal }) => {
      try {
        return await api.get<CandidateFacingMatch>(`/matches/me/jobs/${jobId}`, undefined, { signal })
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 403)) return null
        throw e
      }
    },
    staleTime: 60_000,
  })
}

// --- staff side: ranked candidates per job, match detail, background refresh -----------------------------------------------

export type MatchedCandidate = components['schemas']['MatchedCandidate']
export type RankedCandidatesPage = components['schemas']['RankedCandidatesPage']
export type RankedCandidatesMeta = components['schemas']['RankedCandidatesMeta']
export type MatchDetail = components['schemas']['MatchDetail']
export type ScoreBreakdown = components['schemas']['ScoreBreakdown']
export type TaskOut = components['schemas']['TaskOut']

export interface RankedFilters {
  min_score?: number
  min_experience?: number
  skill_id?: string[]
  location?: string
  availability?: string[]
  applicants_only?: boolean
  page: number
  page_size: number
}

export const staffMatchKeys = {
  all: ['matches'] as const,
  ranked: (jobId: string, f: RankedFilters) => ['matches', 'ranked', jobId, f] as const,
  rankedJob: (jobId: string) => ['matches', 'ranked', jobId] as const,
  detail: (jobId: string, candidateId: string) => ['matches', 'detail', jobId, candidateId] as const,
  task: (taskId: string) => ['tasks', taskId] as const,
}

/** Ranked candidates for a job. Reads persisted scores; the API queues a refresh itself when rows are stale/missing. */
export function useRankedCandidates(jobId: string | undefined, filters: RankedFilters) {
  return useQuery({
    queryKey: staffMatchKeys.ranked(jobId ?? '', filters),
    enabled: Boolean(jobId),
    queryFn: ({ signal }) =>
      api.get<RankedCandidatesPage>(`/matches/jobs/${jobId}/candidates`, { ...filters }, { signal }),
    placeholderData: keepPreviousData,
  })
}

/** Component scores + structured explanation for one candidate/job pair. Resolves to `null` when none was computed. */
export function useMatchDetail(jobId: string | undefined, candidateId: string | undefined) {
  return useQuery({
    queryKey: staffMatchKeys.detail(jobId ?? '', candidateId ?? ''),
    enabled: Boolean(jobId) && Boolean(candidateId),
    queryFn: async ({ signal }) => {
      try {
        return await api.get<MatchDetail>(`/matches/jobs/${jobId}/candidates/${candidateId}`, undefined, {
          signal,
        })
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
  })
}

const TASK_ACTIVE = ['PENDING', 'RUNNING']

/** Polls GET /tasks/{id} every `intervalMs` until it is COMPLETED or FAILED. */
export function useTask(taskId: string | null | undefined, intervalMs = 1500) {
  return useQuery({
    queryKey: staffMatchKeys.task(taskId ?? ''),
    enabled: Boolean(taskId),
    queryFn: ({ signal }) => api.get<TaskOut>(`/tasks/${taskId}`, undefined, { signal }),
    refetchInterval: (q) => (q.state.data && !TASK_ACTIVE.includes(q.state.data.status) ? false : intervalMs),
    staleTime: 0,
    gcTime: 0,
  })
}

/** POST /matches/jobs/{id}/refresh -> 202 + task id. */
export function useRefreshJobMatches(jobId: string) {
  return useMutation({
    mutationFn: () => api.post<{ task_id: string }>(`/matches/jobs/${jobId}/refresh`),
  })
}

/** Called once a refresh task finished: scores, rankings, job stats and candidate match views are all outdated. */
export function useInvalidateMatches() {
  const qc = useQueryClient()
  return (jobId: string) =>
    Promise.all([
      qc.invalidateQueries({ queryKey: staffMatchKeys.all }),
      qc.invalidateQueries({ queryKey: ['jobs', 'stats', jobId] }),
      qc.invalidateQueries({ queryKey: ['candidates'] }),
    ])
}
