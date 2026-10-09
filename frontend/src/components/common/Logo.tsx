import { useId } from 'react'
import { cn } from '@/lib/utils'

/** TalentLens mark: a lens with a check — "finding the right match". */
export function LogoMark({ className }: { className?: string }) {
  // Unique gradient id per instance: a duplicate id inside a display:none ancestor would blank every other logo.
  const gradientId = `tl-logo-${useId().replace(/:/g, '')}`
  return (
    <svg viewBox="0 0 32 32" className={cn('size-8', className)} aria-hidden>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6366f1" />
          <stop offset="1" stopColor="#8b5cf6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${gradientId})`} />
      <circle cx="14.5" cy="14.5" r="6" fill="none" stroke="#fff" strokeWidth="2.6" />
      <path d="M19 19l5.5 5.5" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" />
      <path
        d="M12 14.5l2 2 3.5-3.5"
        fill="none"
        stroke="#fff"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function Logo({ className, showName = true }: { className?: string; showName?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <LogoMark />
      {showName && <span className="text-[17px] font-semibold tracking-tight">TalentLens</span>}
    </span>
  )
}
