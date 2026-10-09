import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react'
import { useNavigation } from 'react-router-dom'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { Role } from '@/lib/api'

export function PageFallback() {
  return (
    <div className="space-y-6" role="status" aria-busy="true" aria-label="Loading page">
      <div className="space-y-2">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-80 max-w-full" />
      </div>
      <Skeleton className="h-64 w-full rounded-xl" />
    </div>
  )
}

type Loader = () => Promise<{ default: ComponentType }>

/** Route-level code splitting: `lazyPage(() => import('…/FooPage'))` -> element with a skeleton fallback. */
export function lazyPage(loader: Loader) {
  const Page = lazy(loader)
  return (
    <Suspense fallback={<PageFallback />}>
      <Page />
    </Suspense>
  )
}

type RolePages = Partial<Record<Role, LazyExoticComponent<ComponentType>>>

/**
 * One URL, a different page per role (/dashboard, /applications, /interviews).
 *   roleSwitch({ CANDIDATE: () => import('…/MyApplicationsPage'), RECRUITER: …, HIRING_MANAGER: …, ADMIN: … })
 */
export function roleSwitch(loaders: Partial<Record<Role, Loader>>) {
  const pages: RolePages = {}
  for (const [role, loader] of Object.entries(loaders) as [Role, Loader][]) pages[role] = lazy(loader)
  return <RoleSwitch pages={pages} />
}

function RoleSwitch({ pages }: { pages: RolePages }) {
  const { user } = useAuth()
  const Page = user ? pages[user.role] : undefined
  if (!Page) return null
  return (
    <Suspense fallback={<PageFallback />}>
      <Page />
    </Suspense>
  )
}

/** Thin top progress bar while a navigation (lazy chunk) is in flight. */
export function NavigationProgress() {
  const { state } = useNavigation()
  if (state === 'idle') return null
  return (
    <div
      role="progressbar"
      aria-label="Loading page"
      className="fixed inset-x-0 top-0 z-[90] h-0.5 animate-pulse bg-primary"
    />
  )
}
