import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface Step {
  id: string
  label: string
  description?: string
}

/** Horizontal progress through ordered steps (hiring pipeline, multi-step forms). `current` is a 0-based index. */
export function Stepper({
  steps,
  current,
  className,
}: {
  steps: Step[]
  current: number
  className?: string
}) {
  return (
    <ol className={cn('flex w-full items-start', className)} aria-label="Progress">
      {steps.map((s, i) => {
        const done = i < current
        const active = i === current
        return (
          <li
            key={s.id}
            className={cn(
              'relative flex flex-1 flex-col items-center gap-1.5 text-center',
              i === 0 && 'items-start text-left',
              i === steps.length - 1 && 'items-end text-right',
            )}
            aria-current={active ? 'step' : undefined}
          >
            {i > 0 && (
              <span
                className={cn(
                  'absolute top-3.5 right-1/2 left-[-50%] h-0.5',
                  i <= current ? 'bg-primary' : 'bg-border',
                )}
                aria-hidden
              />
            )}
            <span
              className={cn(
                'relative z-10 flex size-7 items-center justify-center rounded-full border-2 text-xs font-semibold',
                done && 'border-primary bg-primary text-primary-foreground',
                active && 'border-primary bg-card text-primary',
                !done && !active && 'border-border bg-card text-muted-foreground',
              )}
            >
              {done ? <Check className="size-3.5" strokeWidth={3} aria-hidden /> : i + 1}
            </span>
            <span className={cn('text-xs font-medium', active ? 'text-foreground' : 'text-muted-foreground')}>
              {s.label}
              <span className="sr-only">{done ? ' (completed)' : active ? ' (current step)' : ''}</span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}
