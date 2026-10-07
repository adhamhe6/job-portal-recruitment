import { useQuery } from '@tanstack/react-query'
import { api, ApiError, type CandidateFacingMatch } from '@/lib/api'
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
