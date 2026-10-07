import type * as React from 'react'
import { cn } from '@/lib/utils'

/** Placeholder block for loading states (decorative: hidden from assistive tech). */
export function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return <div aria-hidden className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />
}
