import { format, isValid, parseISO } from 'date-fns'
import type { components } from '@/lib/api'

type S = components['schemas']

export const LANGUAGE_PROFICIENCY_LABELS: Record<S['LanguageProficiency'], string> = {
  BASIC: 'Basic',
  CONVERSATIONAL: 'Conversational',
  FLUENT: 'Fluent',
  NATIVE: 'Native',
}
export const SKILL_PROFICIENCY_LABELS: Record<S['SkillProficiency'], string> = {
  BEGINNER: 'Beginner',
  INTERMEDIATE: 'Intermediate',
  ADVANCED: 'Advanced',
  EXPERT: 'Expert',
}

/** "Mar 2021"; date-only strings parse as local dates. */
export function monthYear(v: string | null | undefined): string {
  if (!v) return ''
  const d = parseISO(v)
  return isValid(d) ? format(d, 'MMM yyyy') : ''
}

export function dateRange(
  start: string | null | undefined,
  end: string | null | undefined,
  current: boolean,
) {
  const from = monthYear(start)
  const to = current ? 'Present' : monthYear(end)
  return [from, to].filter(Boolean).join(' – ')
}

export function yearRange(start: number | null | undefined, end: number | null | undefined) {
  return [start, end].filter((y): y is number => y != null).join(' – ')
}

/** The résumé staff should open by default: primary first, then newest (the API lists newest first). */
export function preferredResume<T extends { is_primary: boolean }>(resumes: readonly T[]): T | undefined {
  return resumes.find((r) => r.is_primary) ?? resumes[0]
}

export function resumeFileName(r: { original_filename?: string | null }, candidateName: string): string {
  return r.original_filename || `${candidateName.replace(/\s+/g, '_')}_resume.pdf`
}
