import { z } from 'zod'
import { optionalPhoneSchema, optionalUrlSchema } from '@/features/auth/lib/schemas'
import type { Option } from '@/lib/enums'
import type {
  Availability,
  CandidateProfile,
  CandidateSkill,
  Certification,
  CertificationIn,
  Education,
  EducationIn,
  Experience,
  ExperienceIn,
  LanguageIn,
  LanguageProficiency,
  ProfileUpdate,
  RemotePreference,
  SkillProficiency,
} from './types'
import type { EducationLevel, EmploymentType } from '@/lib/api'
import { dates } from '@/lib/format'

/**
 * Candidate profile forms: zod schemas mirroring backend/app/schemas/candidate.py (the server stays the source of truth
 * and its field errors are mapped back), plus defaults and API payload mappers. Form values are strings.
 */

export const REMOTE_OPTIONS: Option<RemotePreference>[] = [
  { value: 'ONSITE', label: 'On-site' },
  { value: 'HYBRID', label: 'Hybrid' },
  { value: 'REMOTE', label: 'Remote' },
  { value: 'FLEXIBLE', label: 'Flexible' },
]
export const AVAILABILITY_OPTIONS: Option<Availability>[] = [
  { value: 'IMMEDIATELY', label: 'Immediately' },
  { value: 'TWO_WEEKS', label: 'In two weeks' },
  { value: 'ONE_MONTH', label: 'In one month' },
  { value: 'THREE_MONTHS', label: 'In three months' },
  { value: 'NOT_AVAILABLE', label: 'Not available' },
]
export const PROFICIENCY_OPTIONS: Option<SkillProficiency>[] = [
  { value: 'BEGINNER', label: 'Beginner' },
  { value: 'INTERMEDIATE', label: 'Intermediate' },
  { value: 'ADVANCED', label: 'Advanced' },
  { value: 'EXPERT', label: 'Expert' },
]
export const LANGUAGE_LEVEL_OPTIONS: Option<LanguageProficiency>[] = [
  { value: 'BASIC', label: 'Basic' },
  { value: 'CONVERSATIONAL', label: 'Conversational' },
  { value: 'FLUENT', label: 'Fluent' },
  { value: 'NATIVE', label: 'Native' },
]
export const EMPLOYMENT_PREFERENCE_OPTIONS: Option<EmploymentType>[] = [
  { value: 'FULL_TIME', label: 'Full-time' },
  { value: 'PART_TIME', label: 'Part-time' },
  { value: 'CONTRACT', label: 'Contract' },
  { value: 'INTERNSHIP', label: 'Internship' },
  { value: 'TEMPORARY', label: 'Temporary' },
]

export const labelOf = <V extends string>(options: Option<V>[], value: V | null | undefined) =>
  options.find((o) => o.value === value)?.label ?? ''

const optionalDecimal = (label: string, { max, places }: { max: number; places: number }) =>
  z
    .string()
    .trim()
    .refine((v) => v === '' || /^\d+(\.\d+)?$/.test(v), `${label} must be a number`)
    .refine(
      (v) => v === '' || !/^\d+\.\d+$/.test(v) || (v.split('.')[1]?.length ?? 0) <= places,
      `${label} can have at most ${places} decimal place${places === 1 ? '' : 's'}`,
    )
    .refine((v) => v === '' || Number(v) <= max, `${label} must be at most ${max.toLocaleString('en-US')}`)

const text = (label: string, max: number) =>
  z
    .string()
    .trim()
    .max(max, `${label} must be at most ${max.toLocaleString('en-US')} characters`)
const required = (label: string, max: number) =>
  z
    .string()
    .trim()
    .min(1, `${label} is required`)
    .max(max, `${label} must be at most ${max.toLocaleString('en-US')} characters`)

const isoDate = (label: string) =>
  z.string().refine((v) => v === '' || /^\d{4}-\d{2}-\d{2}$/.test(v), `Enter a valid ${label}`)
const optionalYear = (label: string) =>
  z
    .string()
    .trim()
    .refine((v) => v === '' || /^\d{4}$/.test(v), `${label} must be a 4-digit year`)
    .refine(
      (v) => v === '' || (Number(v) >= 1950 && Number(v) <= 2100),
      `${label} must be between 1950 and 2100`,
    )

/** "example.com" -> "https://example.com"; '' -> null. */
export const normalizeUrl = (v: string): string | null => {
  const t = v.trim()
  if (!t) return null
  return /^https?:\/\//i.test(t) ? t : `https://${t}`
}
const orNull = (v: string): string | null => (v.trim() === '' ? null : v.trim())

// --- basics ----------------------------------------------------------------------------------------------------------

export const basicsSchema = z.object({
  headline: text('Headline', 200),
  summary: text('Summary', 5000),
  location: text('Location', 200),
  phone: optionalPhoneSchema,
  years_experience: optionalDecimal('Years of experience', { max: 70, places: 1 }),
  expected_salary: optionalDecimal('Expected salary', { max: 9_999_999_999, places: 2 }),
  salary_currency: z.string().trim().length(3, 'Choose a 3-letter currency code'),
  remote_preference: z.string(),
  employment_preference: z.string(),
  availability: z.string(),
  portfolio_url: optionalUrlSchema,
  linkedin_url: optionalUrlSchema,
  github_url: optionalUrlSchema,
  is_searchable: z.boolean(),
})
export type BasicsValues = z.infer<typeof basicsSchema>

export const BASICS_FIELDS = Object.keys(basicsSchema.shape)

export function basicsDefaults(p: CandidateProfile): BasicsValues {
  return {
    headline: p.headline ?? '',
    summary: p.summary ?? '',
    location: p.location ?? '',
    phone: p.phone ?? '',
    years_experience: p.years_experience ?? '',
    expected_salary: p.expected_salary ?? '',
    salary_currency: p.salary_currency || 'USD',
    remote_preference: p.remote_preference ?? '',
    employment_preference: p.employment_preference ?? '',
    availability: p.availability ?? '',
    portfolio_url: p.portfolio_url ?? '',
    linkedin_url: p.linkedin_url ?? '',
    github_url: p.github_url ?? '',
    is_searchable: p.is_searchable,
  }
}

export function basicsPayload(v: BasicsValues): ProfileUpdate {
  return {
    headline: orNull(v.headline),
    summary: orNull(v.summary),
    location: orNull(v.location),
    phone: orNull(v.phone),
    years_experience: v.years_experience.trim() === '' ? null : v.years_experience.trim(),
    expected_salary: v.expected_salary.trim() === '' ? null : v.expected_salary.trim(),
    salary_currency: v.salary_currency.toUpperCase(),
    remote_preference: (v.remote_preference || null) as RemotePreference | null,
    employment_preference: (v.employment_preference || null) as EmploymentType | null,
    availability: (v.availability || null) as Availability | null,
    portfolio_url: normalizeUrl(v.portfolio_url),
    linkedin_url: normalizeUrl(v.linkedin_url),
    github_url: normalizeUrl(v.github_url),
    is_searchable: v.is_searchable,
  }
}

// --- skills ----------------------------------------------------------------------------------------------------------

export const skillSchema = z.object({
  proficiency: z.string(),
  years_experience: optionalDecimal('Years of experience', { max: 70, places: 1 }),
})
export type SkillValues = z.infer<typeof skillSchema>

export const skillDefaults = (s?: CandidateSkill): SkillValues => ({
  proficiency: s?.proficiency ?? '',
  years_experience: s?.years_experience ?? '',
})

export const skillBody = (v: SkillValues) => ({
  proficiency: (v.proficiency || null) as SkillProficiency | null,
  years_experience: v.years_experience.trim() === '' ? null : v.years_experience.trim(),
})

// --- experience ------------------------------------------------------------------------------------------------------

export const experienceSchema = z
  .object({
    title: required('Job title', 200),
    company_name: required('Company', 200),
    location: text('Location', 200),
    start_date: isoDate('start date').refine((v) => v !== '', 'Start date is required'),
    end_date: isoDate('end date'),
    is_current: z.boolean(),
    description: text('Description', 5000),
  })
  .superRefine((v, ctx) => {
    if (v.start_date && v.start_date > dates.isoDate())
      ctx.addIssue({ code: 'custom', path: ['start_date'], message: 'Start date cannot be in the future' })
    if (!v.is_current && v.end_date && v.start_date && v.end_date < v.start_date)
      ctx.addIssue({
        code: 'custom',
        path: ['end_date'],
        message: 'End date must not be before the start date',
      })
  })
export type ExperienceValues = z.infer<typeof experienceSchema>

export const experienceDefaults = (e?: Experience): ExperienceValues => ({
  title: e?.title ?? '',
  company_name: e?.company_name ?? '',
  location: e?.location ?? '',
  start_date: e?.start_date ?? '',
  end_date: e?.end_date ?? '',
  is_current: e?.is_current ?? false,
  description: e?.description ?? '',
})

export const experiencePayload = (v: ExperienceValues): ExperienceIn => ({
  title: v.title,
  company_name: v.company_name,
  location: orNull(v.location),
  start_date: v.start_date,
  end_date: v.is_current ? null : orNull(v.end_date),
  is_current: v.is_current,
  description: orNull(v.description),
})

// --- education -------------------------------------------------------------------------------------------------------

export const educationSchema = z
  .object({
    institution: required('Institution', 200),
    degree_level: z.string().min(1, 'Choose a level'),
    degree: text('Degree', 200),
    field_of_study: text('Field of study', 200),
    start_year: optionalYear('Start year'),
    end_year: optionalYear('End year'),
  })
  .superRefine((v, ctx) => {
    if (v.start_year && v.end_year && Number(v.end_year) < Number(v.start_year))
      ctx.addIssue({
        code: 'custom',
        path: ['end_year'],
        message: 'End year must not be before the start year',
      })
  })
export type EducationValues = z.infer<typeof educationSchema>

export const educationDefaults = (e?: Education): EducationValues => ({
  institution: e?.institution ?? '',
  degree_level: e?.degree_level ?? '',
  degree: e?.degree ?? '',
  field_of_study: e?.field_of_study ?? '',
  start_year: e?.start_year ? String(e.start_year) : '',
  end_year: e?.end_year ? String(e.end_year) : '',
})

export const educationPayload = (v: EducationValues): EducationIn => ({
  institution: v.institution,
  degree_level: v.degree_level as EducationLevel,
  degree: orNull(v.degree),
  field_of_study: orNull(v.field_of_study),
  start_year: v.start_year ? Number(v.start_year) : null,
  end_year: v.end_year ? Number(v.end_year) : null,
})

// --- certifications --------------------------------------------------------------------------------------------------

export const certificationSchema = z
  .object({
    name: required('Name', 200),
    issuer: text('Issuer', 200),
    issued_on: isoDate('issue date'),
    expires_on: isoDate('expiry date'),
    credential_url: optionalUrlSchema,
  })
  .superRefine((v, ctx) => {
    if (v.issued_on && v.expires_on && v.expires_on < v.issued_on)
      ctx.addIssue({
        code: 'custom',
        path: ['expires_on'],
        message: 'Expiry must not be before the issue date',
      })
  })
export type CertificationValues = z.infer<typeof certificationSchema>

export const certificationDefaults = (c?: Certification): CertificationValues => ({
  name: c?.name ?? '',
  issuer: c?.issuer ?? '',
  issued_on: c?.issued_on ?? '',
  expires_on: c?.expires_on ?? '',
  credential_url: c?.credential_url ?? '',
})

export const certificationPayload = (v: CertificationValues): CertificationIn => ({
  name: v.name,
  issuer: orNull(v.issuer),
  issued_on: orNull(v.issued_on),
  expires_on: orNull(v.expires_on),
  credential_url: normalizeUrl(v.credential_url),
})

// --- languages -------------------------------------------------------------------------------------------------------

export const languageSchema = z.object({
  language: z
    .string()
    .trim()
    .min(2, 'Language must be at least 2 characters')
    .max(60, 'Language must be at most 60 characters'),
  proficiency: z.string().min(1, 'Choose a level'),
})
export type LanguageValues = z.infer<typeof languageSchema>

export const languagePayload = (v: LanguageValues): LanguageIn => ({
  language: v.language,
  proficiency: v.proficiency as LanguageProficiency,
})
