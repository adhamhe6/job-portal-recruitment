import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type ApplicationCreate, type ApplicationDetail } from '@/lib/api'

export const applicationKeys = { all: ['applications'] as const }

/** POST /applications — apply to a job. Wave-2 (applications module) extends this file with list/detail/withdraw hooks. */
export function useApplyToJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ApplicationCreate) => api.post<ApplicationDetail>('/applications', body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: applicationKeys.all })
      void qc.invalidateQueries({ queryKey: ['jobs'] }) // has_applied / my_application_id flags
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}
