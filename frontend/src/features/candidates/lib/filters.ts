import type { components, QueryParams } from '@/lib/api'
import { EDUCATION_LEVEL_OPTIONS, type Option } from '@/lib/enums'

type S = components['schemas']
export type Availability = S['Availability']
export type RemotePreference = S['RemotePreference']
export type CandidateSort = S['CandidateSort']

export const AVAILABILITY_LABELS: Record<Availability, string> = {
  IMMEDIATELY: 'Immediately',
  TWO_WEEKS: 'Within 2 weeks',
  ONE_MONTH: 'Within 1 month',
  THREE_MONTHS: 'Within 3 months',
  NOT_AVAILABLE: 'Not available',
}
export const REMOTE_PREFERENCE_LABELS: Record<RemotePreference, string> = {
  ONSITE: 'On-site',
  HYBRID: 'Hybrid',
  REMOTE: 'Remote',
  FLEXIBLE: 'Flexible',
}
export const CANDIDATE_SORT_LABELS: Record<CandidateSort, string> = {
  relevance: 'Most relevant',
  match: 'Best job match',
  experience: 'Most experience',
  recent: 'Recently updated',
  name: 'Name A–Z',
}

const toOptions = <V extends string>(labels: Record<V, string>): Option<V>[] =>
  (Object.entries(labels) as [V, string][]).map(([value, label]) => ({ value, label }))
export const AVAILABILITY_OPTIONS = toOptions(AVAILABILITY_LABELS)
export const REMOTE_PREFERENCE_OPTIONS = toOptions(REMOTE_PREFERENCE_LABELS)
export { EDUCATION_LEVEL_OPTIONS }

/**
 * Candidate-search filter state. Plain strings / string[] so it round-trips through the URL
 * (/candidates?q=nlp&skill=Python&skills_mode=all&min_experience=3&job_id=…). Skills travel by NAME.
 */
export const CANDIDATE_SEARCH_DEFAULTS = {
  q: '',
  skill: [] as string[],
  skills_mode: 'all',
  min_experience: '',
  max_experience: '',
  location: '',
  min_education: '',
  certification: '',
  availability: [] as string[],
  remote_preference: [] as string[],
  job_id: '',
  min_match_score: '',
  applicants_only: '',
  sort: 'relevance',
  page: 1,
}
export type CandidateSearchState = typeof CANDIDATE_SEARCH_DEFAULTS

export const CANDIDATE_PAGE_SIZE = 12

const num = (v: string): number | undefined => {
  if (v.trim() === '') return undefined
  const n = Number(v)
  return Number.isFinite(n) && n >= 0 ? n : undefined
}

/** Min-match is typed as a percentage (0-100) in the UI and sent as 0..1. */
export const percentToScore = (v: string): number | undefined => {
  const n = num(v)
  return n === undefined ? undefined : Math.min(1, n / 100)
}

/** Sorting by job match needs a job; without one fall back to relevance (the API would otherwise ignore it). */
export function effectiveSort(f: CandidateSearchState): string {
  return f.sort === 'match' && !f.job_id ? 'relevance' : f.sort
}

/** Client-side check mirroring the API's INVALID_EXPERIENCE_RANGE rule, so we explain it instead of erroring. */
export function experienceRangeError(f: Pick<CandidateSearchState, 'min_experience' | 'max_experience'>) {
  const lo = num(f.min_experience)
  const hi = num(f.max_experience)
  return lo !== undefined && hi !== undefined && lo > hi
    ? 'Minimum experience must not exceed the maximum.'
    : null
}

/** URL state -> GET /search/candidates query parameters. */
export function toSearchQuery(f: CandidateSearchState): QueryParams {
  const invalidRange = experienceRangeError(f) !== null
  return {
    q: f.q.trim() || undefined,
    skill: f.skill,
    skills_mode: f.skill.length > 1 ? f.skills_mode : undefined,
    min_experience: invalidRange ? undefined : num(f.min_experience),
    max_experience: invalidRange ? undefined : num(f.max_experience),
    location: f.location.trim() || undefined,
    min_education: f.min_education || undefined,
    certification: f.certification.trim() || undefined,
    availability: f.availability,
    remote_preference: f.remote_preference,
    job_id: f.job_id || undefined,
    min_match_score: f.job_id ? percentToScore(f.min_match_score) : undefined,
    applicants_only: f.applicants_only === 'true' ? true : undefined,
    sort: effectiveSort(f),
    page: f.page,
    page_size: CANDIDATE_PAGE_SIZE,
  }
}

/** Number of active filters (excluding keyword, sort, page). */
export function countActiveFilters(f: CandidateSearchState): number {
  return (
    f.skill.length +
    (f.min_experience || f.max_experience ? 1 : 0) +
    (f.location.trim() ? 1 : 0) +
    (f.min_education ? 1 : 0) +
    (f.certification.trim() ? 1 : 0) +
    f.availability.length +
    f.remote_preference.length +
    (f.job_id ? 1 : 0) +
    (f.job_id && f.min_match_score ? 1 : 0) +
    (f.applicants_only === 'true' ? 1 : 0)
  )
}
