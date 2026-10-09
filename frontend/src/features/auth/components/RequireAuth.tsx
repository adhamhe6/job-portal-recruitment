import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation, useSearchParams } from 'react-router-dom'
import ForbiddenPage from '@/pages/ForbiddenPage'
import type { Role } from '@/lib/api'
import type { Permission } from '@/lib/permissions'
import { safeRedirect } from '@/lib/utils'
import { loginUrl, paths } from '@/routes/paths'
import { useAuth } from '../hooks/useAuth'

/**
 * Route guard.
 *  - anonymous  -> /login?next=<where they were going> (nothing after an explicit sign-out)
 *  - signed in but wrong role / missing permission -> in-place 403 page (URL kept)
 * Use as a layout route (renders <Outlet/>) or wrapping children.
 *
 *   { element: <RequireAuth roles={['RECRUITER','ADMIN']} />, children: [...] }
 */
export function RequireAuth({
  roles,
  permission,
  children,
}: {
  roles?: readonly Role[]
  permission?: Permission
  children?: ReactNode
}) {
  const { status, user, can, justLoggedOut } = useAuth()
  const location = useLocation()
  if (status !== 'authenticated' || !user) {
    const next = location.pathname + location.search
    return <Navigate to={justLoggedOut ? paths.login : loginUrl(next)} replace />
  }
  if ((roles && !roles.includes(user.role)) || (permission && !can(permission))) return <ForbiddenPage />
  return <>{children ?? <Outlet />}</>
}

/** Login / register pages: signed-in users are sent on to `?next=` (or the dashboard). */
export function RequireGuest({ children }: { children?: ReactNode }) {
  const { status } = useAuth()
  const [params] = useSearchParams()
  if (status === 'authenticated')
    return <Navigate to={safeRedirect(params.get('next'), paths.dashboard)} replace />
  return <>{children ?? <Outlet />}</>
}
