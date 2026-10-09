import type {
  ApplyRequest,
  ApplyResult,
  ExtractedCertification,
  ExtractedEducation,
  ExtractedExperience,
  ExtractedLanguage,
  ExtractedResume,
  ExtractedSkill,
  ProfileField,
} from '../api/resumes'
import type { CandidateProfile } from '@/features/profile/lib/types'

/** Pure helpers for the suggestion-review flow (selection defaults, apply payload, wording). */

export type ListSection = 'skills' | 'experiences' | 'educations' | 'certifications' | 'languages'
export const LIST_SECTIONS: ListSection[] = [
  'skills',
  'experiences',
  'educations',
  'certifications',
  'languages',
]

export type Suggestion =
  ExtractedSkill | ExtractedExperience | ExtractedEducation | ExtractedCertification | ExtractedLanguage

/** Why a suggestion cannot be applied as-is (null = it can). */
export function blocker(section: ListSection, item: Suggestion): string | null {
  if (item.already_on_profile) return 'Already on your profile'
  if (section === 'skills') {
    const s = item as ExtractedSkill
    if (!s.skill_id) return 'Not in the skill library — edit the name to match one'
    return null
  }
  if ('missing_for_apply' in item && item.missing_for_apply.length > 0)
    return `Missing ${item.missing_for_apply.map((f) => f.replace(/_/g, ' ')).join(', ')} — edit to complete`
  return null
}

export const isApplicable = (section: ListSection, item: Suggestion) => blocker(section, item) === null

export function confidenceLabel(c: number): { label: string; variant: 'success' | 'warning' | 'muted' } {
  if (c >= 0.8) return { label: 'High confidence', variant: 'success' }
  if (c >= 0.5) return { label: 'Medium confidence', variant: 'warning' }
  return { label: 'Low confidence', variant: 'muted' }
}

export interface ScalarSuggestion {
  field: ProfileField
  label: string
  suggested: string
  current: string
}

const str = (v: unknown) => (v === null || v === undefined ? '' : String(v).trim())

/** The profile fields the résumé can fill, with the suggested and the current value side by side. */
export function scalarSuggestions(
  data: ExtractedResume,
  profile: CandidateProfile | undefined,
): ScalarSuggestion[] {
  const rows: [ProfileField, string, string, string][] = [
    ['headline', 'Headline', str(data.headline), str(profile?.headline)],
    ['summary', 'Summary', str(data.summary), str(profile?.summary)],
    [
      'years_experience',
      'Years of experience',
      data.years_of_experience != null ? String(data.years_of_experience) : '',
      str(profile?.years_experience),
    ],
    ['location', 'Location', str(data.contact.location), str(profile?.location)],
    ['phone', 'Phone', str(data.contact.phone), str(profile?.phone)],
    ['linkedin_url', 'LinkedIn', str(data.contact.linkedin_url), str(profile?.linkedin_url)],
    ['github_url', 'GitHub', str(data.contact.github_url), str(profile?.github_url)],
    ['portfolio_url', 'Portfolio', str(data.contact.portfolio_url), str(profile?.portfolio_url)],
  ]
  return rows
    .filter(([, , suggested]) => suggested !== '')
    .map(([field, label, suggested, current]) => ({ field, label, suggested, current }))
}

/** Same number with different formatting (e.g. "5.5" vs "5.50") is not a conflict. */
export const sameValue = (a: string, b: string) =>
  a === b || (a !== '' && b !== '' && !Number.isNaN(Number(a)) && Number(a) === Number(b))

export interface Selection {
  lists: Record<ListSection, number[]>
  /** Fields to fill. */
  fields: ProfileField[]
  /** Fields that may replace an existing value (explicit opt-in per field). */
  overwrite: ProfileField[]
}

/** Default: every applicable list item; scalar fields only where the profile is still empty (never overwrite). */
export function defaultSelection(data: ExtractedResume, profile: CandidateProfile | undefined): Selection {
  const lists = Object.fromEntries(
    LIST_SECTIONS.map((s) => [
      s,
      (data[s] as Suggestion[]).filter((i) => isApplicable(s, i)).map((i) => i.index),
    ]),
  ) as Record<ListSection, number[]>
  const fields = scalarSuggestions(data, profile)
    .filter((r) => r.current === '')
    .map((r) => r.field)
  return { lists, fields, overwrite: [] }
}

export function selectionCount(sel: Selection): number {
  return LIST_SECTIONS.reduce((n, s) => n + sel.lists[s].length, 0) + sel.fields.length
}

/** The selection restricted to suggestions that still exist and can be applied. */
export function effectiveSelection(sel: Selection, data: ExtractedResume): Selection {
  const lists = Object.fromEntries(
    LIST_SECTIONS.map((s) => {
      const ok = new Set((data[s] as Suggestion[]).filter((i) => isApplicable(s, i)).map((i) => i.index))
      return [s, sel.lists[s].filter((i) => ok.has(i))]
    }),
  ) as Record<ListSection, number[]>
  return { ...sel, lists, overwrite: sel.overwrite.filter((f) => sel.fields.includes(f)) }
}

export function toApplyRequest(sel: Selection, data: ExtractedResume): ApplyRequest {
  const { lists, fields, overwrite } = effectiveSelection(sel, data)
  return { ...lists, fields, overwrite }
}

const SKIP_REASONS: Record<string, string> = {
  ALREADY_ON_PROFILE: 'already on your profile',
  NOT_FOUND: 'no longer available',
  REMOVED: 'you rejected it',
  UNKNOWN_SKILL: 'not in the skill library',
  FIELD_NOT_EMPTY: 'your existing value was kept',
  NO_SUGGESTION: 'nothing was suggested',
  INVALID_URL: 'the link is not a valid web address',
}

export function skipText(reason: string): string {
  if (SKIP_REASONS[reason]) return SKIP_REASONS[reason]
  if (reason.startsWith('MISSING_')) return `missing ${reason.slice(8).toLowerCase().replace(/_/g, ' ')}`
  if (reason.startsWith('INVALID_')) return `invalid ${reason.slice(8).toLowerCase().replace(/_/g, ' ')}`
  return reason.toLowerCase().replace(/_/g, ' ')
}

const SECTION_NOUN: Record<string, [string, string]> = {
  skills: ['skill', 'skills'],
  experiences: ['work experience', 'work experiences'],
  educations: ['education entry', 'education entries'],
  certifications: ['certification', 'certifications'],
  languages: ['language', 'languages'],
}

export function applySummary(result: ApplyResult): string {
  const parts = Object.entries(result.applied)
    .filter(([, n]) => n > 0)
    .map(([section, n]) => `${n} ${SECTION_NOUN[section]?.[n === 1 ? 0 : 1] ?? section}`)
  if (result.fields_applied.length > 0)
    parts.push(
      `${result.fields_applied.length} profile field${result.fields_applied.length === 1 ? '' : 's'}`,
    )
  return parts.length
    ? `Added to your profile: ${parts.join(', ')}.`
    : 'Nothing new was added to your profile.'
}

export const sectionLabel = (section: string) => {
  const raw = section.startsWith('profile.') ? section.slice(8) : section
  return SECTION_NOUN[raw]?.[0] ?? raw.replace(/_/g, ' ')
}
