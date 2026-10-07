import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Label } from './label'

interface ControlProps {
  id?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean | 'true' | 'false'
  'aria-required'?: boolean
}

/**
 * Label + control + help text + error message, wired together for assistive tech:
 * the control gets `id`, `aria-describedby` (help and/or error), `aria-invalid` and `aria-required`.
 * The error is rendered with role="alert" so it is announced when it appears.
 *
 *   <Field label="Title" error={errors.title?.message} required><Input {...register('title')} /></Field>
 */
export function Field({
  label,
  hint,
  error,
  required,
  optional,
  htmlFor,
  className,
  labelClassName,
  children,
}: {
  label: ReactNode
  hint?: ReactNode
  error?: string | null
  required?: boolean
  optional?: boolean
  /** Use when the child is not a single element that accepts `id` (e.g. a composite widget). */
  htmlFor?: string
  className?: string
  labelClassName?: string
  children: ReactNode
}) {
  const autoId = useId()
  const child = isValidElement(children) ? (children as ReactElement<ControlProps>) : null
  const id = htmlFor ?? child?.props.id ?? autoId
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [child?.props['aria-describedby'], hintId, errorId].filter(Boolean).join(' ') || undefined

  const control = child
    ? cloneElement(child, {
        id,
        'aria-describedby': describedBy,
        'aria-invalid': error ? true : child.props['aria-invalid'],
        'aria-required': required ? true : child.props['aria-required'],
      })
    : children

  return (
    <div className={cn('grid gap-1.5', className)}>
      <Label htmlFor={id} className={labelClassName}>
        {label}
        {required && (
          <span className="ml-0.5 text-destructive" aria-hidden>
            *
          </span>
        )}
        {optional && <span className="ml-1.5 text-xs font-normal text-muted-foreground">Optional</span>}
      </Label>
      {control}
      {hint && !error && (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
