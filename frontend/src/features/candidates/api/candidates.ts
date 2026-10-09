import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, type components, type Paginated } from '@/lib/api'
import { toSearchQuery, type CandidateSearchState } from '../lib/filters'

type S = components['schemas']
export type CandidateListItem = S['CandidateListItem']
export type CandidateView = S['CandidateView']
export type CandidateSkillOut = S['CandidateSkillOut']
export type ApplicationBrief = S['ApplicationBrief']
export type ResumeBrief = S['ResumeBrief']

/** Everything candidate-related lives under ['candidates', …] so one invalidation refreshes searches and details. */
export const candidateKeys = {
  all: ['candidates'] as const,
  search: (f: CandidateSearchState) => ['candidates', 'search', f] as const,
  detail: (id: string, jobId: string) => ['candidates', 'detail', id, jobId] as const,
}

/** Staff candidate search. The API only returns candidates visible to the caller's company. */
export function useCandidateSearch(filters: CandidateSearchState, enabled = true) {
  return useQuery({
    enabled,
    queryKey: candidateKeys.search(filters),
    queryFn: ({ signal }) =>
      api.get<Paginated<CandidateListItem>>('/search/candidates', toSearchQuery(filters), { signal }),
    placeholderData: keepPreviousData,
  })
}

/** Shape of `CandidateView.match` (the schema types it as a free-form object). */
export interface CandidateMatchSummary {
  job_id: string
  overall_score: number
  semantic_score?: number | null
  required_skill_score?: number | null
  preferred_skill_score?: number | null
  experience_score?: number | null
  education_score?: number | null
  preference_score?: number | null
  explanation?: Record<string, unknown>
}

/** Staff view of one candidate; pass `jobId` to include that job's match explanation. */
export function useCandidate(id: string | undefined, jobId = '') {
  return useQuery({
    queryKey: candidateKeys.detail(id ?? '', jobId),
    queryFn: ({ signal }) =>
      api.get<CandidateView>(`/candidates/${id}`, { job_id: jobId || undefined }, { signal }),
    enabled: Boolean(id),
  })
}
