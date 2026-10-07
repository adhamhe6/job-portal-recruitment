import { Check, Circle, Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'
import type * as React from 'react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/** Password field with a show/hide toggle. Pass `autoComplete="current-password"` or `"new-password"`. */
export function PasswordInput({ className, ...props }: Omit<React.ComponentProps<'input'>, 'type'>) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <Input type={visible ? 'text' : 'password'} className={cn('pr-10', className)} {...props} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
        className="absolute top-1/2 right-1.5 inline-flex size-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        {visible ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
      </button>
    </div>
  )
}

export const PASSWORD_RULES = [
  { id: 'length', label: 'At least 10 characters', test: (v: string) => v.length >= 10 },
  { id: 'letter', label: 'Contains a letter', test: (v: string) => /[A-Za-z]/.test(v) },
  { id: 'digit', label: 'Contains a number', test: (v: string) => /\d/.test(v) },
] as const

/** Live checklist of the backend's password rules. */
export function PasswordRules({ value, id }: { value: string; id?: string }) {
  return (
    <ul id={id} className="grid gap-1 text-xs" aria-label="Password requirements">
      {PASSWORD_RULES.map((r) => {
        const ok = r.test(value)
        return (
          <li key={r.id} className={cn('flex items-center gap-1.5', ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-muted-foreground')}>
            {ok ? <Check className="size-3.5" aria-hidden /> : <Circle className="size-3.5" aria-hidden />}
            {r.label}
            <span className="sr-only">{ok ? ' (met)' : ' (not met yet)'}</span>
          </li>
        )
      })}
    </ul>
  )
}
