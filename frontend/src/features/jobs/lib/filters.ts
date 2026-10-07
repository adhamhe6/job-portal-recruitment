import type { QueryParams } from '@/lib/api'

/**
 * Job-search filter state. Every field is a plain string / string[] so it round-trips through the URL
 * (/jobs?q=python&skill=Postgres&skills_mode=all&workplace_type=REMOTE&sort=newest&page=2).
 * Skills travel by NAME (the API resolves names and aliases), which keeps links human-readable and shareable.
 */
export const JOB_SEARCH_DEFAULTS = {
  q: '',
  skill: [] as string[],
  skills_mode: 'any',
  location: '',
  employment_type: [] as string[],
  workplace_type: [] as string[],
  experience_level: [] as string[],
  max_experience: '',
  salary_min: '',
  salary_max: '',
  posted_within_days: '',
  company_id: '',
  sort: 'relevance',
  page: 1,
}

export type JobSearchState = typeof JOB_SEARCH_DEFAULTS

export const JOB_SEARCH_PAGE_SIZE = 10

const num = (v: string): number | undefined => {
  if (v.trim() === '') return undefined
  const n = Number(v)
  return Number.isFinite(n) && n >= 0 ? n : undefined
}

/** URL state -> GET /search/jobs query parameters. */
export function toSearchQuery(f: JobSearchState): QueryParams {
  return {
    q: f.q.trim() || undefined,
    skill: f.skill,
    skills_mode: f.skill.length > 1 ? f.skills_mode : undefined,
    location: f.location.trim() || undefined,
    employment_type: f.employment_type,
    workplace_type: f.workplace_type,
    experience_level: f.experience_level,
    max_experience: num(f.max_experience),
    salary_min: num(f.salary_min),
    salary_max: num(f.salary_max),
    posted_within_days: num(f.posted_within_days),
    company_id: f.company_id || undefined,
    sort: f.sort !== 'relevance' || f.q.trim() ? f.sort : 'newest',
    page: f.page,
    page_size: JOB_SEARCH_PAGE_SIZE,
  }
}

/** Number of active filters (excluding keyword, sort, page) - drives the mobile "Filters (n)" badge. */
export function countActiveFilters(f: JobSearchState): number {
  return (
    f.skill.length +
    (f.location.trim() ? 1 : 0) +
    f.employment_type.length +
    f.workplace_type.length +
    f.experience_level.length +
    (f.max_experience ? 1 : 0) +
    (f.salary_min || f.salary_max ? 1 : 0) +
    (f.posted_within_days ? 1 : 0) +
    (f.company_id ? 1 : 0)
  )
}
