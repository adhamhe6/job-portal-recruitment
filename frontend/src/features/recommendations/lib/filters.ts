import type { EmploymentType, WorkplaceType } from '@/lib/api'
import type { PickedSkill } from '@/features/skills/components/SkillPicker'
import type { Option } from '@/lib/enums'

export const MIN_SCORE_OPTIONS: Option[] = [
  { value: '35', label: 'Partial or better (35%+)' },
  { value: '55', label: 'Good or better (55%+)' },
  { value: '75', label: 'Strong only (75%+)' },
]
export const SORT_OPTIONS: Option[] = [
  { value: 'score', label: 'Best match' },
  { value: 'newest', label: 'Newest' },
]

export const asWorkplace = (v: string[]) => v as WorkplaceType[]
export const asEmployment = (v: string[]) => v as EmploymentType[]

/** Skills live in the URL as `id~Name` so the chips can be rebuilt without a lookup. */
export const encodeSkill = (s: PickedSkill) => `${s.id ?? ''}~${s.name}`
export function decodeSkill(v: string): PickedSkill | null {
  const i = v.indexOf('~')
  if (i <= 0) return null
  return { id: v.slice(0, i), name: v.slice(i + 1) }
}
