import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type components, type EmploymentType, type WorkplaceType } from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'

export type RecommendationsPage = components['schemas']['RecommendationsPage']
export type RecommendedJob = components['schemas']['RecommendedJob']
export type RecommendationsMeta = components['schemas']['RecommendationsMeta']
type TaskRef = components['schemas']['TaskRef']

export interface RecommendationFilters {
  /** Minimum match, in percent (0-100). */
  minScore: number
  workplace: WorkplaceType[]
  employment: EmploymentType[]
  location: string
  skillIds: string[]
  sort: 'score' | 'newest'
  page: number
  pageSize?: number
}

export const recommendationKeys = {
  all: ['recommendations'] as const,
  list: (f: RecommendationFilters) => ['recommendations', 'jobs', f] as const,
}

/** Ranked jobs for the signed-in candidate (only open jobs they have not applied to). */
export function useRecommendations(filters: RecommendationFilters) {
  const { isCandidate } = useAuth()
  const f = { pageSize: 10, ...filters }
  return useQuery({
    queryKey: recommendationKeys.list(f),
    enabled: isCandidate,
    queryFn: ({ signal }) =>
      api.get<RecommendationsPage>(
        '/recommendations/jobs',
        {
          min_score: f.minScore > 0 ? f.minScore / 100 : undefined,
          workplace_type: f.workplace,
          employment_type: f.employment,
          location: f.location || undefined,
          skill_id: f.skillIds,
          sort: f.sort,
          page: f.page,
          page_size: f.pageSize,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

/** Queue a background recompute (POST /recommendations/refresh → 202 + task id; poll it with useTask). */
export function useRefreshRecommendations() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<TaskRef>('/recommendations/refresh'),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: recommendationKeys.all }) // meta.computing flips to true
    },
  })
}
