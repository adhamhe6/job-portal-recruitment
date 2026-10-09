import { cva, type VariantProps } from 'class-variance-authority'
import type * as React from 'react'
import { cn } from '@/lib/utils'

export const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap [&_svg]:size-3 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary-soft text-primary-soft-foreground',
        solid: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'border-border bg-transparent text-foreground',
        muted: 'border-transparent bg-muted text-muted-foreground',
        success:
          'border-transparent bg-emerald-500/12 text-emerald-800 dark:bg-emerald-400/15 dark:text-emerald-300',
        warning: 'border-transparent bg-amber-500/15 text-amber-900 dark:bg-amber-400/15 dark:text-amber-300',
        danger: 'border-transparent bg-red-500/12 text-red-800 dark:bg-red-400/15 dark:text-red-300',
        info: 'border-transparent bg-sky-500/12 text-sky-800 dark:bg-sky-400/15 dark:text-sky-300',
        violet:
          'border-transparent bg-violet-500/12 text-violet-800 dark:bg-violet-400/15 dark:text-violet-300',
        orange:
          'border-transparent bg-orange-500/15 text-orange-900 dark:bg-orange-400/15 dark:text-orange-300',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps extends React.ComponentProps<'span'>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
