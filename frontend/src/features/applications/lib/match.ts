/** Defensive reader for the free-form `explanation` object of GET /matches/jobs/{id}/candidates/{cid}. */

export interface SkillGroup {
  total: number
  matched: string[]
  missing: string[]
  related: { required: string; candidateHas: string }[]
}
export interface MatchInsight {
  summary: string | null
  required: SkillGroup
  preferred: SkillGroup
  experienceText: string | null
  experienceStatus: string | null
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)

function names(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  return v
    .map((x) => (typeof x === 'string' ? x : isObj(x) ? str(x.name) : null))
    .filter((x): x is string => x !== null)
}

function group(v: unknown): SkillGroup {
  const o = isObj(v) ? v : {}
  const related = Array.isArray(o.related)
    ? o.related
        .filter(isObj)
        .map((r) => ({ required: str(r.required) ?? '', candidateHas: str(r.candidate_has) ?? '' }))
        .filter((r) => r.required)
    : []
  return {
    total: typeof o.total === 'number' ? o.total : 0,
    matched: names(o.matched),
    missing: names(o.missing),
    related,
  }
}

export function parseExplanation(explanation: unknown): MatchInsight {
  const e = isObj(explanation) ? explanation : {}
  const skills = isObj(e.skills) ? e.skills : {}
  const exp = isObj(e.experience) ? e.experience : {}
  return {
    summary: str(e.summary),
    required: group(skills.required),
    preferred: group(skills.preferred),
    experienceText: str(exp.text),
    experienceStatus: str(exp.status),
  }
}
