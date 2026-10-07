import { useQuery } from '@tanstack/react-query'
import { api, ApiError } from '@/lib/api'

export interface DemoAccount {
  role: string
  label: string
  email: string
}

interface Meta {
  demo_mode: boolean
  demo_password?: string | null
  demo_accounts?: DemoAccount[]
}

/**
 * Fallback used ONLY when GET /meta is unavailable (404) and VITE_SHOW_DEMO_ACCOUNTS === 'true'.
 * The condition is a build-time constant, so production bundles without the flag contain none of this.
 */
const FALLBACK: { accounts: DemoAccount[]; password: string } | null =
  import.meta.env.VITE_SHOW_DEMO_ACCOUNTS === 'true'
    ? {
        password: 'DemoPass123!',
        accounts: [
          { role: 'CANDIDATE', label: 'Candidate — Alex Rivera', email: 'candidate@demo.example' },
          { role: 'RECRUITER', label: 'Recruiter — Northwind Labs', email: 'recruiter@demo.example' },
          { role: 'HIRING_MANAGER', label: 'Hiring manager — Northwind Labs', email: 'hiring.manager@demo.example' },
          { role: 'ADMIN', label: 'Platform admin', email: 'admin@demo.example' },
        ],
      }
    : null

export interface DemoAccounts {
  accounts: DemoAccount[]
  password: string
}

/** One-click demo sign-in shortcuts: from GET /meta in demo mode; otherwise the env-flag fallback; otherwise none. */
export function useDemoAccounts(): DemoAccounts | null {
  const { data, isPending } = useQuery({
    queryKey: ['meta'],
    queryFn: async ({ signal }) => {
      try {
        return await api.get<Meta>('/meta', undefined, { signal })
      } catch (e) {
        if (e instanceof ApiError) return null // 404 (endpoint absent) or any API error -> fall back to the env flag
        throw e
      }
    },
    staleTime: Infinity,
    retry: false,
  })
  if (isPending) return null
  if (data) {
    if (!data.demo_mode || !data.demo_accounts?.length || !data.demo_password) return null
    return { accounts: data.demo_accounts, password: data.demo_password }
  }
  return FALLBACK
}
