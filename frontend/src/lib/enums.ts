import type {
  ApplicationStatus,
  EducationLevel,
  EmploymentType,
  ExperienceLevel,
  JobSort,
  JobStatus,
  Role,
  WorkplaceType,
} from './api/types'

/** Display labels + option lists for API enums. Single source of truth for selects, filters and badges. */

export interface Option<V extends string = string> {
  value: V
  label: string
}

const toOptions = <V extends string>(labels: Record<V, string>): Option<V>[] =>
  (Object.entries(labels) as [V, string][]).map(([value, label]) => ({ value, label }))

export const EMPLOYMENT_TYPE_LABELS: Record<EmploymentType, string> = {
  FULL_TIME: 'Full-time',
  PART_TIME: 'Part-time',
  CONTRACT: 'Contract',
  INTERNSHIP: 'Internship',
  TEMPORARY: 'Temporary',
}
export const WORKPLACE_TYPE_LABELS: Record<WorkplaceType, string> = {
  ONSITE: 'On-site',
  HYBRID: 'Hybrid',
  REMOTE: 'Remote',
}
export const EXPERIENCE_LEVEL_LABELS: Record<ExperienceLevel, string> = {
  ENTRY: 'Entry level',
  JUNIOR: 'Junior',
  MID: 'Mid level',
  SENIOR: 'Senior',
  LEAD: 'Lead / Principal',
}
export const EDUCATION_LEVEL_LABELS: Record<EducationLevel, string> = {
  HIGH_SCHOOL: 'High school',
  ASSOCIATE: 'Associate degree',
  BACHELOR: "Bachelor's degree",
  MASTER: "Master's degree",
  DOCTORATE: 'Doctorate',
}
export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  DRAFT: 'Draft',
  PUBLISHED: 'Published',
  PAUSED: 'Paused',
  CLOSED: 'Closed',
  ARCHIVED: 'Archived',
}
export const APPLICATION_STATUS_LABELS: Record<ApplicationStatus, string> = {
  APPLIED: 'Applied',
  SCREENING: 'Screening',
  SHORTLISTED: 'Shortlisted',
  INTERVIEW: 'Interview',
  OFFER: 'Offer',
  HIRED: 'Hired',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
}
export const ROLE_LABELS: Record<Role, string> = {
  ADMIN: 'Administrator',
  RECRUITER: 'Recruiter',
  HIRING_MANAGER: 'Hiring manager',
  CANDIDATE: 'Candidate',
}
export const JOB_SORT_LABELS: Record<JobSort, string> = {
  relevance: 'Most relevant',
  newest: 'Newest',
  salary_desc: 'Salary: high to low',
  salary_asc: 'Salary: low to high',
  deadline: 'Deadline: soonest',
  match: 'Best match',
  title: 'Title A–Z',
}

export const EMPLOYMENT_TYPE_OPTIONS = toOptions(EMPLOYMENT_TYPE_LABELS)
export const WORKPLACE_TYPE_OPTIONS = toOptions(WORKPLACE_TYPE_LABELS)
export const EXPERIENCE_LEVEL_OPTIONS = toOptions(EXPERIENCE_LEVEL_LABELS)
export const EDUCATION_LEVEL_OPTIONS = toOptions(EDUCATION_LEVEL_LABELS)
export const JOB_STATUS_OPTIONS = toOptions(JOB_STATUS_LABELS)

/** ISO-4217 codes offered in the job form (an existing job's own currency is always added). */
export const CURRENCIES = ['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'CHF', 'SEK', 'NOK', 'DKK', 'PLN', 'INR', 'AED', 'SAR', 'SGD', 'JPY'] as const

export const POSTED_WITHIN_OPTIONS: Option[] = [
  { value: '1', label: 'Last 24 hours' },
  { value: '7', label: 'Last 7 days' },
  { value: '14', label: 'Last 14 days' },
  { value: '30', label: 'Last 30 days' },
]
