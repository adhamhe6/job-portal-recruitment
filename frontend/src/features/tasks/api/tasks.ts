import { useQuery } from '@tanstack/react-query'
import { api, type components } from '@/lib/api'

export type TaskOut = components['schemas']['TaskOut']

export const taskKeys = { detail: (id: string) => ['tasks', id] as const }

export const TASK_POLL_MS = 1_500

export const isTaskDone = (t: Pick<TaskOut, 'status'> | undefined) =>
  t?.status === 'COMPLETED' || t?.status === 'FAILED'

/** Background task status (GET /tasks/{id}); refetches every 1.5 s until COMPLETED or FAILED. */
export function useTask(taskId: string | null | undefined) {
  return useQuery({
    queryKey: taskKeys.detail(taskId ?? ''),
    enabled: Boolean(taskId),
    queryFn: ({ signal }) => api.get<TaskOut>(`/tasks/${taskId}`, undefined, { signal }),
    refetchInterval: (query) => (isTaskDone(query.state.data) ? false : TASK_POLL_MS),
    staleTime: 0,
    gcTime: 60_000,
  })
}
