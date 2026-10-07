import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { ErrorState, Spinner } from '@/components/common/States'
import { ApiError, onSessionExpired, onSessionRefreshed, refreshSession, tokenStore, type Me, type Role, type TokenResponse } from '@/lib/api'
import type { Permission } from '@/lib/permissions'
import { authApi } from '../api/auth'
import { AuthContext, type AuthContextValue, type AuthStatus } from '../hooks/useAuth'

interface State {
  status: AuthStatus
  user: Me | null
}

/**
 * Owns the session. The access token lives in memory (lib/api/client.ts); on page load we try one silent refresh
 * (HttpOnly cookie) to restore the session before rendering the app, so no query ever fires with the wrong identity.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [state, setState] = useState<State>({ status: 'loading', user: null })
  const [bootError, setBootError] = useState<ApiError | null>(null)
  const [justLoggedOut, setJustLoggedOut] = useState(false)
  const hadUser = useRef(false)

  const applySession = useCallback((data: TokenResponse) => {
    tokenStore.set(data.access_token)
    hadUser.current = true
    setState({ status: 'authenticated', user: data.user })
    return data.user
  }, [])

  const clearSession = useCallback(() => {
    tokenStore.set(null)
    hadUser.current = false
    qc.clear() // never leak one user's cached data to the next
    setState({ status: 'anonymous', user: null })
  }, [qc])

  const restore = useCallback(
    () =>
      refreshSession()
        .then((data) => {
          if (data) applySession(data)
          else setState({ status: 'anonymous', user: null })
        })
        .catch((e: unknown) => setBootError(e instanceof ApiError ? e : new ApiError(0, 'NETWORK_ERROR', 'Cannot reach the server.'))),
    [applySession],
  )

  // One silent refresh on load. (Single-flight in the client makes StrictMode's double effect harmless.)
  useEffect(() => {
    void restore()
  }, [restore])

  const retryRestore = useCallback(() => {
    setBootError(null)
    setState({ status: 'loading', user: null })
    void restore()
  }, [restore])

  useEffect(
    () =>
      onSessionExpired(() => {
        if (!hadUser.current) return
        toast.info('Your session expired. Please sign in again.')
        clearSession()
      }),
    [clearSession],
  )

  // Silent refreshes performed by the API client carry a fresh user + permissions.
  useEffect(() => onSessionRefreshed((data) => setState((s) => (s.status === 'authenticated' ? { status: 'authenticated', user: data.user } : s))), [])

  const login = useCallback(
    async (email: string, password: string) => {
      const data = await authApi.login(email, password)
      qc.clear()
      setJustLoggedOut(false)
      return applySession(data)
    },
    [applySession, qc],
  )
  const registerCandidate = useCallback<AuthContextValue['registerCandidate']>(
    async (payload) => {
      const data = await authApi.registerCandidate(payload)
      qc.clear()
      setJustLoggedOut(false)
      return applySession(data)
    },
    [applySession, qc],
  )
  const registerEmployer = useCallback<AuthContextValue['registerEmployer']>(
    async (payload) => {
      const data = await authApi.registerEmployer(payload)
      qc.clear()
      setJustLoggedOut(false)
      return applySession(data)
    },
    [applySession, qc],
  )
  const logout = useCallback(async () => {
    setJustLoggedOut(true)
    try {
      await authApi.logout()
    } catch {
      /* the refresh cookie may already be gone; local sign-out must still succeed */
    }
    clearSession()
  }, [clearSession])
  const setUser = useCallback((user: Me) => setState((s) => (s.status === 'authenticated' ? { ...s, user } : s)), [])

  const value = useMemo<AuthContextValue>(() => {
    const user = state.user
    const permissions = new Set<string>(user?.permissions ?? [])
    const role = user?.role
    return {
      status: state.status,
      user,
      justLoggedOut,
      permissions,
      can: (p: Permission) => permissions.has(p),
      hasRole: (...roles: Role[]) => (role ? roles.includes(role) : false),
      isCandidate: role === 'CANDIDATE',
      isStaff: role === 'RECRUITER' || role === 'HIRING_MANAGER',
      isAdmin: role === 'ADMIN',
      login,
      registerCandidate,
      registerEmployer,
      logout,
      setUser,
    }
  }, [state, justLoggedOut, login, registerCandidate, registerEmployer, logout, setUser])

  if (bootError) {
    return (
      <div className="flex min-h-dvh items-center justify-center p-6">
        <ErrorState error={bootError} onRetry={retryRestore} title="TalentLens can't connect right now" />
      </div>
    )
  }
  if (state.status === 'loading') {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Spinner label="Loading TalentLens" />
      </div>
    )
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
