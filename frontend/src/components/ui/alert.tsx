import { cva, type VariantProps } from 'class-variance-authority'
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

const alertVariants = cva('flex gap-3 rounded-lg border p-3.5 text-sm', {
  variants: {
    variant: {
      info: 'border-sky-500/30 bg-sky-500/8 text-sky-950 dark:text-sky-100',
      success: 'border-emerald-500/30 bg-emerald-500/8 text-emerald-950 dark:text-emerald-100',
      warning: 'border-amber-500/40 bg-amber-500/10 text-amber-950 dark:text-amber-100',
      danger: 'border-red-500/30 bg-red-500/8 text-red-950 dark:text-red-100',
    },
  },
  defaultVariants: { variant: 'info' },
})

const ICONS = { info: Info, success: CheckCircle2, warning: AlertTriangle, danger: XCircle }
const ICON_TONE = {
  info: 'text-sky-600 dark:text-sky-400',
  success: 'text-emerald-600 dark:text-emerald-400',
  warning: 'text-amber-600 dark:text-amber-400',
  danger: 'text-red-600 dark:text-red-400',
}

/** Inline banner. `danger` uses role="alert" (announced immediately); others use role="status". */
export function Alert({
  variant = 'info',
  title,
  children,
  action,
  className,
}: VariantProps<typeof alertVariants> & { title?: ReactNode; children?: ReactNode; action?: ReactNode; className?: string }) {
  const v = variant ?? 'info'
  const Icon = ICONS[v]
  return (
    <div role={v === 'danger' ? 'alert' : 'status'} className={cn(alertVariants({ variant }), className)}>
      <Icon className={cn('mt-0.5 size-4.5 shrink-0', ICON_TONE[v])} aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className="leading-relaxed [&_a]:font-medium [&_a]:underline [&_ul]:list-disc [&_ul]:pl-5">{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}
