import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { api, type NotificationOut, type Paginated, type UnreadCount } from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'

/** Query keys: ['notifications', 'list', params] / ['notifications', 'unread-count'] — invalidate ['notifications'] for both. */
export const notificationKeys = {
  all: ['notifications'] as const,
  list: (params: { page: number; pageSize: number; unreadOnly: boolean }) =>
    ['notifications', 'list', params] as const,
  unread: ['notifications', 'unread-count'] as const,
}

export const UNREAD_POLL_MS = 45_000

/** Unread badge count; polls every 45 s while the tab is visible. */
export function useUnreadCount() {
  const { status } = useAuth()
  return useQuery({
    queryKey: notificationKeys.unread,
    queryFn: ({ signal }) => api.get<UnreadCount>('/notifications/unread-count', undefined, { signal }),
    enabled: status === 'authenticated',
    refetchInterval: UNREAD_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: 15_000,
    select: (d) => d.unread,
  })
}

export function useNotifications(
  params: { page?: number; pageSize?: number; unreadOnly?: boolean; enabled?: boolean } = {},
) {
  const { page = 1, pageSize = 10, unreadOnly = false, enabled = true } = params
  return useQuery({
    queryKey: notificationKeys.list({ page, pageSize, unreadOnly }),
    queryFn: ({ signal }) =>
      api.get<Paginated<NotificationOut>>(
        '/notifications',
        { page, page_size: pageSize, unread_only: unreadOnly || undefined },
        { signal },
      ),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  })
}

function patchLists(qc: QueryClient, fn: (items: NotificationOut[]) => NotificationOut[]) {
  qc.setQueriesData<Paginated<NotificationOut>>({ queryKey: ['notifications', 'list'] }, (old) =>
    old ? { ...old, items: fn(old.items) } : old,
  )
}

export function useMarkRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<NotificationOut>(`/notifications/${id}/read`),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: notificationKeys.all })
      const wasUnread = qc
        .getQueriesData<Paginated<NotificationOut>>({ queryKey: ['notifications', 'list'] })
        .some(([, d]) => d?.items.some((n) => n.id === id && !n.is_read))
      patchLists(qc, (items) =>
        items.map((n) =>
          n.id === id ? { ...n, is_read: true, read_at: n.read_at ?? new Date().toISOString() } : n,
        ),
      )
      if (wasUnread)
        qc.setQueryData<UnreadCount>(notificationKeys.unread, (old) =>
          old ? { unread: Math.max(0, old.unread - 1) } : old,
        )
    },
    onSettled: () => qc.invalidateQueries({ queryKey: notificationKeys.all }),
  })
}

export function useMarkAllRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<UnreadCount>('/notifications/read-all'),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: notificationKeys.all })
      patchLists(qc, (items) =>
        items.map((n) => ({ ...n, is_read: true, read_at: n.read_at ?? new Date().toISOString() })),
      )
      qc.setQueryData<UnreadCount>(notificationKeys.unread, { unread: 0 })
    },
    onSettled: () => qc.invalidateQueries({ queryKey: notificationKeys.all }),
  })
}
