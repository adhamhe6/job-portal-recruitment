import { z } from 'zod'
import type {
  EducationLevel,
  EmploymentType,
  ExperienceLevel,
  JobCreate,
  JobDetail,
  JobUpdate,
  SkillRequirement,
  WorkplaceType,
} from '@/lib/api'
import { dates } from '@/lib/format'

/**
 * Job form: schema, defaults and API payload mapping.
 * The rules mirror backend/app/schemas/job.py (the server remains the source of truth and its field errors are
 * mapped back onto the form): title 3-200, description 10-20 000, salary_min <= salary_max, experience min <= max,
 * deadline not in the past, 3-letter currency. Publishing additionally needs a 30+ character description and at
 * least one REQUIRED skill (services/jobs.py::_publish_problems).
 */

const EMPLOYMENT: [EmploymentType, ...EmploymentType[]] = [
  'FULL_TIME',
  'PART_TIME',
  'CONTRACT',
  'INTERNSHIP',
  'TEMPORARY',
]
const WORKPLACE: [WorkplaceType, ...WorkplaceType[]] = ['ONSITE', 'HYBRID', 'REMOTE']
const LEVELS: [ExperienceLevel, ...ExperienceLevel[]] = ['ENTRY', 'JUNIOR', 'MID', 'SENIOR', 'LEAD']
const EDUCATION: [EducationLevel, ...EducationLevel[]] = [
  'HIGH_SCHOOL',
  'ASSOCIATE',
  'BACHELOR',
  'MASTER',
  'DOCTORATE',
]
const REQUIREMENT: [SkillRequirement, ...SkillRequirement[]] = ['REQUIRED', 'PREFERRED']

/** Optional non-negative decimal typed as a string ('' allowed). */
const decimal = (label: string, { max, places }: { max: number; places: number }) =>
  z
    .string()
    .trim()
    .refine((v) => v === '' || /^\d+(\.\d+)?$/.test(v), `${label} must be a number`)
    .refine(
      (v) => v === '' || !/^\d+\.\d+$/.test(v) || (v.split('.')[1]?.length ?? 0) <= places,
      `${label} can have at most ${places} decimal place${places === 1 ? '' : 's'}`,
    )
    .refine((v) => v === '' || Number(v) <= max, `${label} must be at most ${max.toLocaleString('en-US')}`)

export const skillRowSchema = z.object({
  skill_id: z.string().optional(),
  name: z.string().trim().min(1, 'Skill name is required').max(100),
  requirement: z.enum(REQUIREMENT),
  min_years: decimal('Years', { max: 30, places: 1 }),
})

export function buildJobSchema({ originalDeadline }: { originalDeadline?: string | null } = {}) {
  return z
    .object({
      title: z
        .string()
        .trim()
        .min(3, 'Title must be at least 3 characters')
        .max(200, 'Title must be at most 200 characters'),
      department: z.string().trim().max(100, 'Department must be at most 100 characters'),
      location: z.string().trim().max(200, 'Location must be at most 200 characters'),
      employment_type: z.enum(EMPLOYMENT),
      workplace_type: z.enum(WORKPLACE),
      experience_level: z.enum(['', ...LEVELS]),
      description: z
        .string()
        .trim()
        .min(10, 'Description must be at least 10 characters')
        .max(20000, 'Description must be at most 20,000 characters'),
      responsibilities: z.string().max(10000, 'Responsibilities must be at most 10,000 characters'),
      qualifications: z.string().max(10000, 'Qualifications must be at most 10,000 characters'),
      benefits: z.string().max(5000, 'Benefits must be at most 5,000 characters'),
      min_experience_years: decimal('Minimum experience', { max: 70, places: 1 }),
      max_experience_years: decimal('Maximum experience', { max: 70, places: 1 }),
      min_education_level: z.enum(['', ...EDUCATION]),
      salary_min: decimal('Minimum salary', { max: 9_999_999_999, places: 2 }),
      salary_max: decimal('Maximum salary', { max: 9_999_999_999, places: 2 }),
      salary_currency: z.string().trim().length(3, 'Choose a 3-letter currency code'),
      application_deadline: z
        .string()
        .refine((v) => v === '' || /^\d{4}-\d{2}-\d{2}$/.test(v), 'Enter a valid date')
        .refine(
          (v) => v === '' || v === (originalDeadline ?? '') || v >= dates.isoDate(),
          'Deadline cannot be in the past',
        ),
      hiring_manager_id: z.string(),
      skills: z.array(skillRowSchema).max(40, 'A job can list at most 40 skills'),
    })
    .superRefine((v, ctx) => {
      if (v.salary_min !== '' && v.salary_max !== '' && Number(v.salary_max) < Number(v.salary_min)) {
        ctx.addIssue({
          code: 'custom',
          path: ['salary_max'],
          message: 'Maximum salary must be at least the minimum',
        })
      }
      if (
        v.max_experience_years !== '' &&
        Number(v.max_experience_years) < Number(v.min_experience_years || 0)
      ) {
        ctx.addIssue({
          code: 'custom',
          path: ['max_experience_years'],
          message: 'Maximum experience must be at least the minimum',
        })
      }
      const seen = new Set<string>()
      v.skills.forEach((s, i) => {
        const key = (s.skill_id ?? s.name).toLowerCase()
        if (seen.has(key))
          ctx.addIssue({ code: 'custom', path: ['skills', i, 'name'], message: `${s.name} is listed twice` })
        seen.add(key)
      })
    })
}

export type JobFormValues = z.infer<ReturnType<typeof buildJobSchema>>

export const EMPTY_JOB_FORM: JobFormValues = {
  title: '',
  department: '',
  location: '',
  employment_type: 'FULL_TIME',
  workplace_type: 'ONSITE',
  experience_level: '',
  description: '',
  responsibilities: '',
  qualifications: '',
  benefits: '',
  min_experience_years: '0',
  max_experience_years: '',
  min_education_level: '',
  salary_min: '',
  salary_max: '',
  salary_currency: 'USD',
  application_deadline: '',
  hiring_manager_id: '',
  skills: [],
}

const trimZeros = (v: string | null | undefined): string => {
  if (v === null || v === undefined || v === '') return ''
  const n = Number(v)
  return Number.isFinite(n) ? String(n) : ''
}

export function jobToFormValues(job: JobDetail): JobFormValues {
  return {
    title: job.title,
    department: job.department ?? '',
    location: job.location ?? '',
    employment_type: job.employment_type,
    workplace_type: job.workplace_type,
    experience_level: job.experience_level ?? '',
    description: job.description,
    responsibilities: job.responsibilities ?? '',
    qualifications: job.qualifications ?? '',
    benefits: job.benefits ?? '',
    min_experience_years: trimZeros(job.min_experience_years) || '0',
    max_experience_years: trimZeros(job.max_experience_years),
    min_education_level: job.min_education_level ?? '',
    salary_min: trimZeros(job.salary_min),
    salary_max: trimZeros(job.salary_max),
    salary_currency: job.salary_currency,
    application_deadline: job.application_deadline ?? '',
    hiring_manager_id: job.hiring_manager_id ?? '',
    skills: job.skills.map((s) => ({
      skill_id: s.skill.id,
      name: s.skill.name,
      requirement: s.requirement,
      min_years: trimZeros(s.min_years),
    })),
  }
}

const orNull = (v: string): string | null => (v.trim() === '' ? null : v.trim())
const numOrNull = (v: string): number | null => (v.trim() === '' ? null : Number(v))

/** Form -> API body. Cleared optional fields are sent as explicit nulls so PATCH really clears them. */
export function formValuesToPayload(v: JobFormValues): JobCreate & JobUpdate {
  return {
    title: v.title.trim(),
    department: orNull(v.department),
    location: orNull(v.location),
    employment_type: v.employment_type,
    workplace_type: v.workplace_type,
    experience_level: v.experience_level || null,
    description: v.description.trim(),
    responsibilities: orNull(v.responsibilities),
    qualifications: orNull(v.qualifications),
    benefits: orNull(v.benefits),
    min_experience_years: Number(v.min_experience_years || 0),
    max_experience_years: numOrNull(v.max_experience_years),
    min_education_level: v.min_education_level || null,
    salary_min: numOrNull(v.salary_min),
    salary_max: numOrNull(v.salary_max),
    salary_currency: v.salary_currency.toUpperCase(),
    application_deadline: orNull(v.application_deadline),
    hiring_manager_id: orNull(v.hiring_manager_id),
    skills: v.skills.map((s) => ({
      ...(s.skill_id ? { skill_id: s.skill_id } : { name: s.name.trim() }),
      requirement: s.requirement,
      min_years: numOrNull(s.min_years),
    })),
  }
}

export interface PublishProblem {
  field: keyof JobFormValues
  message: string
}

/** Client-side mirror of the backend's publish gate, so the user sees what is missing before any round-trip. */
export function publishProblems(v: JobFormValues): PublishProblem[] {
  const problems: PublishProblem[] = []
  if (v.description.trim().length < 30)
    problems.push({ field: 'description', message: 'Description must be at least 30 characters to publish' })
  if (!v.skills.some((s) => s.requirement === 'REQUIRED'))
    problems.push({ field: 'skills', message: 'Add at least one required skill to publish' })
  if (v.application_deadline && v.application_deadline < dates.isoDate())
    problems.push({ field: 'application_deadline', message: 'The application deadline is in the past' })
  return problems
}

/** Maps backend error codes / messages onto form fields. */
export const JOB_FORM_FIELDS = Object.keys(EMPTY_JOB_FORM)
export const JOB_ERROR_CODE_FIELDS: Record<string, string> = {
  DUPLICATE_JOB: 'title',
  INVALID_SALARY_RANGE: 'salary_max',
  INVALID_EXPERIENCE_RANGE: 'max_experience_years',
  INVALID_DEADLINE: 'application_deadline',
  INVALID_HIRING_MANAGER: 'hiring_manager_id',
  SKILL_NOT_FOUND: 'skills',
}
export function inferJobField(message: string): string | undefined {
  const m = message.toLowerCase()
  if (m.includes('salary_max') || m.includes('salary_min')) return 'salary_max'
  if (m.includes('max_experience') || m.includes('min_experience')) return 'max_experience_years'
  if (m.includes('deadline')) return 'application_deadline'
  return undefined
}
