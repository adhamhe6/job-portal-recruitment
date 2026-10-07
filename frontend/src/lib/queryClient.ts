import { MutationCache, QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from '@/lib/api'

/**
 * One factory for the app and for tests.
 * - queries: 30 s staleTime, no refetch on window focus, no retries for 4xx (auth / validation / not-found are not transient)
 * - mutations: a global `meta.errorToast` hook is available via `meta: { errorToast: 'Could not save' }`
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
          return count < 2
        },
      },
    },
    mutationCache: new MutationCache({
      onError: (error, _vars, _ctx, mutation) => {
        const msg = mutation.meta?.errorToast
        if (typeof msg === 'string') toast.error(msg, { description: error instanceof Error ? error.message : undefined })
      },
    }),
  })
}
