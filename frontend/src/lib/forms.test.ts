import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api'
import { applyApiErrors } from './forms'

const FIELDS = ['title', 'salary_max', 'skills', 'email'] as const

describe('applyApiErrors', () => {
  it('attaches validation issues to matching fields (top-level segment of dotted paths) and returns leftovers', () => {
    const setError = vi.fn()
    const err = new ApiError(422, 'VALIDATION_ERROR', 'Request validation failed', [
      { field: 'title', message: 'Too short', type: 'x' },
      { field: 'skills.0', message: 'Value error, provide skill_id or name', type: 'value_error' },
      { field: 'unknown_field', message: 'Weird', type: 'x' },
    ])
    const left = applyApiErrors(err, setError, { fields: FIELDS })
    expect(setError).toHaveBeenCalledWith('title', { type: 'server', message: 'Too short' }, { shouldFocus: false })
    expect(setError).toHaveBeenCalledWith('skills', { type: 'server', message: 'provide skill_id or name' }, { shouldFocus: false })
    expect(left).toBe('unknown_field: Weird')
  })

  it('maps business codes and infers fields for model-level errors', () => {
    const setError = vi.fn()
    expect(applyApiErrors(new ApiError(409, 'EMAIL_ALREADY_REGISTERED', 'Taken'), setError, { fields: FIELDS, codeFields: { EMAIL_ALREADY_REGISTERED: 'email' } })).toBeNull()
    expect(setError).toHaveBeenCalledWith('email', { type: 'server', message: 'Taken' }, expect.anything())

    const inferred = new ApiError(422, 'VALIDATION_ERROR', 'x', [{ field: '', message: 'Value error, salary_max must be >= salary_min', type: 'value_error' }])
    expect(applyApiErrors(inferred, setError, { fields: FIELDS, inferField: (m) => (m.includes('salary_max') ? 'salary_max' : undefined) })).toBeNull()
    expect(setError).toHaveBeenCalledWith('salary_max', { type: 'server', message: 'salary_max must be >= salary_min' }, expect.anything())
  })

  it('falls back to the error message for everything else', () => {
    const setError = vi.fn()
    expect(applyApiErrors(new ApiError(500, 'INTERNAL_ERROR', 'Boom'), setError, { fields: FIELDS })).toBe('Boom')
    expect(applyApiErrors(new Error('plain'), setError, { fields: FIELDS })).toBe('plain')
    expect(setError).not.toHaveBeenCalled()
  })
})
