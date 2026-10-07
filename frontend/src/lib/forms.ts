import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'
import { ApiError } from '@/lib/api'

/**
 * Map a failed API call onto a react-hook-form instance.
 *
 *  - 422 VALIDATION_ERROR `details[]` ({field, message}) -> `setError(field)` for every field that exists in the form
 *  - `codeFields` maps business error codes to a field (e.g. EMAIL_ALREADY_REGISTERED -> 'email')
 *  - `inferField` can attribute messages with an empty `field` (model-level validators) to a form field
 *
 * Returns the message that should be shown as a form-level alert (or null when everything was attached to fields).
 */
export function applyApiErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  opts: {
    fields: readonly string[]
    /** API field path -> form field (e.g. { 'skills.0': 'skills' }). Top-level segment is tried automatically. */
    fieldMap?: Record<string, string>
    codeFields?: Record<string, string>
    inferField?: (message: string) => string | undefined
  },
): string | null {
  if (!(error instanceof ApiError))
    return error instanceof Error ? error.message : 'Something went wrong. Please try again.'

  const known = new Set(opts.fields)
  const attach = (field: string, message: string): boolean => {
    if (!known.has(field)) return false
    setError(field as Path<T>, { type: 'server', message }, { shouldFocus: false })
    return true
  }

  const fieldForCode = opts.codeFields?.[error.code]
  if (fieldForCode && attach(fieldForCode, error.message)) return null

  const general: string[] = []
  const issues = error.fieldIssues
  if (issues.length === 0) return error.message

  for (const issue of issues) {
    const mapped = opts.fieldMap?.[issue.field] ?? issue.field
    const top = mapped.split('.')[0] ?? ''
    const inferred = !mapped ? opts.inferField?.(issue.message) : undefined
    if (
      attach(mapped, issue.message) ||
      attach(top, issue.message) ||
      (inferred && attach(inferred, issue.message))
    )
      continue
    general.push(issue.field ? `${issue.field}: ${issue.message}` : issue.message)
  }
  return general.length ? general.join(' · ') : null
}

/** Scroll to and focus the first invalid field after a failed submit (RHF only focuses registered inputs). */
export function focusFirstError() {
  requestAnimationFrame(() => {
    const el = document.querySelector<HTMLElement>('[aria-invalid="true"]')
    el?.focus({ preventScroll: false })
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  })
}
