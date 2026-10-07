import { createContext, useContext, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** Which layout a page is currently rendered in. Public-but-personalised pages render in both. */
export const LayoutKindContext = createContext<'public' | 'app'>('app')

/**
 * Page width/padding wrapper for pages that can appear in either layout: the app shell already pads and constrains
 * <main>, the public layout does not (so full-bleed pages like the landing hero are possible).
 */
export function PageContainer({ children, className }: { children: ReactNode; className?: string }) {
  const kind = useContext(LayoutKindContext)
  if (kind === 'app') return <>{children}</>
  return <div className={cn('mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8', className)}>{children}</div>
}
