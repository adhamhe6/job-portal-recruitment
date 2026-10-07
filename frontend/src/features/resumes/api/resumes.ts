import { useQuery } from '@tanstack/react-query'
import { api, ApiError, type Paginated } from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'

/**
 * Résumé summary as exposed to the apply flow. GET /resumes is owned by the résumé module (wave 2) and is not in the
 * OpenAPI schema yet, so the minimal shape we depend on is declared here (see ResumeBrief in the schema for the target).
 */
export interface ResumeSummary {
  id: string
  original_filename?: string | null
  is_primary?: boolean
  status?: string
  created_at?: string
}

export const resumeKeys = { list: ['resumes', 'list'] as const }

/** The candidate's résumés. A missing endpoint (404/405) or an empty list both resolve to `[]`. */
export function useMyResumes(enabled = true) {
  const { isCandidate } = useAuth()
  return useQuery({
    queryKey: resumeKeys.list,
    enabled: enabled && isCandidate,
    queryFn: async ({ signal }): Promise<ResumeSummary[]> => {
      try {
        const data = await api.get<ResumeSummary[] | Paginated<ResumeSummary>>('/resumes', undefined, { signal })
        return Array.isArray(data) ? data : (data?.items ?? [])
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return []
        throw e
      }
    },
    staleTime: 30_000,
  })
}
