import { createContext, useContext } from 'react'
import type { Me, RegisterCandidateRequest, RegisterEmployerRequest, Role } from '@/lib/api'
import type { Permission } from '@/lib/permissions'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  status: AuthStatus
  user: Me | null
  /** True right after an explicit sign-out (route guards then skip the "return to this page" redirect). */
  justLoggedOut: boolean
  permissions: ReadonlySet<string>
  /** Does the current user hold this backend permission (e.g. `can('manage_jobs')`)? */
  can: (permission: Permission) => boolean
  hasRole: (...roles: Role[]) => boolean
  isCandidate: boolean
  isStaff: boolean
  isAdmin: boolean
  login: (email: string, password: string) => Promise<Me>
  registerCandidate: (data: RegisterCandidateRequest) => Promise<Me>
  registerEmployer: (data: RegisterEmployerRequest) => Promise<Me>
  logout: () => Promise<void>
  /** Replace the cached user (after PATCH /auth/me). */
  setUser: (user: Me) => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** For components rendered under <RequireAuth>: the signed-in user, never null. */
export function useCurrentUser(): Me {
  const { user } = useAuth()
  if (!user) throw new Error('useCurrentUser requires an authenticated session (wrap the route in <RequireAuth>)')
  return user
}
