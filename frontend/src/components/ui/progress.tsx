import { cn } from '@/lib/utils'

export function Progress({
  value,
  label,
  className,
  indicatorClassName,
}: {
  /** 0..100 */
  value: number
  /** Accessible name (required for screen readers). */
  label: string
  className?: string
  indicatorClassName?: string
}) {
  const v = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v)}
      aria-label={label}
      className={cn('h-2 w-full overflow-hidden rounded-full bg-muted', className)}
    >
      <div
        className={cn(
          'h-full rounded-full bg-primary transition-[width] duration-500 ease-out',
          indicatorClassName,
        )}
        style={{ width: `${v}%` }}
      />
    </div>
  )
}
