import type { RankedFilters, ScoreBreakdown } from '@/features/matches/api/matches'

/** The six components of the overall score, in the order the backend weights them (matching/scoring.py). */
export const SCORE_COMPONENTS = [
  {
    key: 'semantic',
    weightKey: 'semantic',
    label: 'Profile relevance',
    help: 'How close the meaning of the résumé and profile is to the job description (text embeddings).',
  },
  {
    key: 'required_skills',
    weightKey: 'required',
    label: 'Required skills',
    help: 'Share of the job’s required skills the candidate has. Related skills count partially.',
  },
  {
    key: 'preferred_skills',
    weightKey: 'preferred',
    label: 'Preferred skills',
    help: 'Share of the nice-to-have skills the candidate has.',
  },
  {
    key: 'experience',
    weightKey: 'experience',
    label: 'Experience',
    help: 'Years of experience compared with the range the job asks for.',
  },
  {
    key: 'education',
    weightKey: 'education',
    label: 'Education',
    help: 'Highest education level compared with the job’s minimum.',
  },
  {
    key: 'preferences',
    weightKey: 'preference',
    label: 'Preferences',
    help: 'Location, workplace type and employment type compared with what the candidate prefers.',
  },
] as const satisfies readonly {
  key: keyof ScoreBreakdown
  weightKey: string
  label: string
  help: string
}[]

export const SCORE_DISCLAIMER =
  'The score is a ranking aid that orders candidates by how well their profile fits this job’s requirements. It is not a prediction of job performance or a hiring decision: it can miss context a person would see, and a lower score does not mean a candidate is unsuitable. Always review the profile and the explanation before deciding.'

// --- ranked-candidates filter state (kept in the URL) ---------------------------------------------------------------------------

export const MATCHING_DEFAULTS = {
  min_score: '',
  applicants_only: '',
  min_experience: '',
  location: '',
  availability: [] as string[],
  page: 1,
}
export type MatchingFilterState = typeof MATCHING_DEFAULTS

export const MATCHING_PAGE_SIZE = 10

const num = (v: string): number | undefined => {
  if (v.trim() === '') return undefined
  const n = Number(v)
  return Number.isFinite(n) && n >= 0 ? n : undefined
}

/** `min_score` is typed as a percentage in the UI and sent as 0..1. */
export function toRankedFilters(f: MatchingFilterState): RankedFilters {
  const pct = num(f.min_score)
  const params: RankedFilters = {
    page: f.page,
    page_size: MATCHING_PAGE_SIZE,
  }
  if (pct !== undefined) params.min_score = Math.min(1, pct / 100)
  const exp = num(f.min_experience)
  if (exp !== undefined) params.min_experience = exp
  if (f.location.trim()) params.location = f.location.trim()
  if (f.availability.length) params.availability = f.availability
  if (f.applicants_only === 'true') params.applicants_only = true
  return params
}

export function countActiveFilters(f: MatchingFilterState): number {
  return (
    (num(f.min_score) !== undefined ? 1 : 0) +
    (f.applicants_only === 'true' ? 1 : 0) +
    (num(f.min_experience) !== undefined ? 1 : 0) +
    (f.location.trim() ? 1 : 0) +
    f.availability.length
  )
}

// --- explanation parsing -------------------------------------------------------------------------------------------------------------

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)
const strings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
const numOrNull = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const strOrNull = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)

export interface SkillGroup {
  total: number
  coverage: number | null
  matched: string[]
  missing: string[]
  related: { required: string; candidateHas: string }[]
}

export interface ParsedExplanation {
  summary: string | null
  required: SkillGroup | null
  preferred: SkillGroup | null
  weights: Record<string, number>
  semantic: { band: string | null; score: number | null } | null
  experience: { text: string | null; status: string | null } | null
  education: { status: string | null; required: string | null; candidate: string | null } | null
  preferences: { label: string; value: string }[]
  qualificationFloorApplied: boolean
}

function parseGroup(v: unknown): SkillGroup | null {
  if (!isRecord(v)) return null
  const matched = Array.isArray(v.matched)
    ? v.matched.flatMap((m) =>
        isRecord(m) && typeof m.name === 'string' ? [m.name] : typeof m === 'string' ? [m] : [],
      )
    : []
  const related = Array.isArray(v.related)
    ? v.related.flatMap((r) =>
        isRecord(r)
          ? [{ required: strOrNull(r.required) ?? '?', candidateHas: strOrNull(r.candidate_has) ?? '?' }]
          : [],
      )
    : []
  return {
    total: numOrNull(v.total) ?? matched.length,
    coverage: numOrNull(v.coverage),
    matched,
    missing: strings(v.missing),
    related,
  }
}

/** `MatchDetail.explanation` is a free-form object in the schema; read it defensively. */
export function parseExplanation(raw: Record<string, unknown> | null | undefined): ParsedExplanation {
  const e = raw ?? {}
  const skills = isRecord(e.skills) ? e.skills : {}
  const weights: Record<string, number> = {}
  if (isRecord(e.weights))
    for (const [k, v] of Object.entries(e.weights)) {
      const n = numOrNull(v)
      if (n !== null) weights[k] = n
    }
  const sem = isRecord(e.semantic) ? e.semantic : null
  const exp = isRecord(e.experience) ? e.experience : null
  const edu = isRecord(e.education) ? e.education : null
  const prefs = isRecord(e.preferences) ? e.preferences : {}
  const prefLabels: Record<string, string> = {
    location: 'Location',
    workplace: 'Workplace',
    employment: 'Employment type',
  }
  return {
    summary: strOrNull(e.summary),
    required: parseGroup(skills.required),
    preferred: parseGroup(skills.preferred),
    weights,
    semantic: sem ? { band: strOrNull(sem.band), score: numOrNull(sem.score) } : null,
    experience: exp ? { text: strOrNull(exp.text), status: strOrNull(exp.status) } : null,
    education: edu
      ? {
          status: strOrNull(edu.status),
          required: strOrNull(edu.required_level),
          candidate: strOrNull(edu.candidate_level),
        }
      : null,
    preferences: Object.entries(prefs).flatMap(([k, v]) =>
      typeof v === 'string' && v ? [{ label: prefLabels[k] ?? k, value: v }] : [],
    ),
    qualificationFloorApplied: e.qualification_floor_applied === true,
  }
}

export const SEMANTIC_LABELS: Record<string, string> = {
  HIGH: 'High',
  MEDIUM: 'Medium',
  MED: 'Medium',
  LOW: 'Low',
}
export const REQUIREMENT_STATUS_LABELS: Record<string, string> = {
  MEETS: 'Meets the requirement',
  EXCEEDS: 'Exceeds the requirement',
  ABOVE: 'Exceeds the requirement',
  BELOW: 'Below the requirement',
  UNKNOWN: 'Not enough information',
  NOT_REQUIRED: 'Not required',
}
