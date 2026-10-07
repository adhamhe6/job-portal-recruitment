import { X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export type SkillChipTone = 'default' | 'required' | 'preferred' | 'matched' | 'missing' | 'related' | 'muted'

const TONES: Record<SkillChipTone, string> = {
  default: 'bg-secondary text-secondary-foreground',
  required: 'bg-primary-soft text-primary-soft-foreground',
  preferred: 'border-dashed border-border bg-transparent text-muted-foreground',
  matched: 'bg-emerald-500/12 text-emerald-800 dark:bg-emerald-400/15 dark:text-emerald-300',
  missing: 'bg-red-500/10 text-red-800 dark:bg-red-400/15 dark:text-red-300',
  related: 'bg-amber-500/15 text-amber-900 dark:bg-amber-400/15 dark:text-amber-300',
  muted: 'bg-muted text-muted-foreground',
}

/** Skill pill. Optionally removable. `tone` conveys meaning (required/preferred/matched/missing/related). */
export function SkillChip({
  name,
  tone = 'default',
  onRemove,
  className,
  prefix,
}: {
  name: string
  tone?: SkillChipTone
  onRemove?: () => void
  className?: string
  /** e.g. a check icon */
  prefix?: React.ReactNode
}) {
  return (
    <Badge variant="outline" className={cn('border-transparent font-medium', TONES[tone], onRemove && 'pr-1', className)}>
      {prefix}
      {name}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${name}`}
          className="inline-flex size-4 cursor-pointer items-center justify-center rounded-full hover:bg-black/10 dark:hover:bg-white/15"
        >
          <X className="size-3" aria-hidden />
        </button>
      )}
    </Badge>
  )
}

/** A wrapped row of chips with a "+N" overflow. */
export function SkillChipList({ names, max = 5, tone = 'default', className }: { names: string[]; max?: number; tone?: SkillChipTone; className?: string }) {
  const shown = names.slice(0, max)
  const rest = names.length - shown.length
  return (
    <ul className={cn('flex flex-wrap gap-1.5', className)} aria-label="Skills">
      {shown.map((n) => (
        <li key={n}>
          <SkillChip name={n} tone={tone} />
        </li>
      ))}
      {rest > 0 && (
        <li>
          <SkillChip name={`+${rest}`} tone="muted" />
        </li>
      )}
    </ul>
  )
}
