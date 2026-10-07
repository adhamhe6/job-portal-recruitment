import { useAuth } from '@/features/auth/hooks/useAuth'
import { AppShell } from './AppShell'
import { PublicLayout } from './PublicLayout'

/**
 * Public-but-personalised routes (/jobs, /jobs/:id): visitors get the marketing layout,
 * signed-in users get the application shell (sidebar, notifications) around the very same page.
 */
export function AdaptiveLayout() {
  const { status } = useAuth()
  return status === 'authenticated' ? <AppShell /> : <PublicLayout />
}
