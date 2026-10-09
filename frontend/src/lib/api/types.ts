import type { components } from './schema'

/**
 * Convenient aliases over the generated OpenAPI schema (src/lib/api/schema.d.ts, produced by `npm run gen:api`).
 * Import API types from here (or from '@/lib/api'), never hand-write response shapes that the schema already has.
 */
type S = components['schemas']

// Enums
export type Role = S['Role']
export type JobStatus = S['JobStatus']
export type EmploymentType = S['EmploymentType']
export type WorkplaceType = S['WorkplaceType']
export type ExperienceLevel = S['ExperienceLevel']
export type EducationLevel = S['EducationLevel']
export type SkillRequirement = S['SkillRequirement']
export type ApplicationStatus = S['ApplicationStatus']
export type NotificationType = S['NotificationType']
export type CompanySize = S['CompanySize']
export type JobSort = S['JobSort']

// Auth
export type Me = S['MeOut']
export type TokenResponse = S['TokenResponse']
export type LoginRequest = S['LoginRequest']
export type RegisterCandidateRequest = S['RegisterCandidateRequest']
export type RegisterEmployerRequest = S['RegisterEmployerRequest']
export type UpdateMeRequest = S['UpdateMeRequest']
export type ChangePasswordRequest = S['ChangePasswordRequest']

// Jobs
export type JobListItem = S['JobListItem']
export type JobPublic = S['JobPublic']
export type JobDetail = S['JobDetail']
export type JobSkillOut = S['JobSkillOut']
export type JobSkillIn = S['JobSkillIn']
export type JobCreate = S['JobCreate']
export type JobUpdate = S['JobUpdate']
export type JobStats = S['JobStats']
export type JobTransition = S['JobTransition']

// Companies, skills, matches, notifications, applications
export type CompanyPublic = S['CompanyPublic']
export type CompanyOut = S['CompanyOut']
export type MemberOut = S['MemberOut']
export type SkillOut = S['SkillOut']
export type SkillCreate = S['SkillCreate']
export type CandidateFacingMatch = S['CandidateFacingMatch']
export type NotificationOut = S['NotificationOut']
export type UnreadCount = S['UnreadCount']
export type ApplicationCreate = S['ApplicationCreate']
export type ApplicationDetail = S['ApplicationDetail']
export type ApplicationListItem = S['ApplicationListItem']
export type ResumeBrief = S['ResumeBrief']

/** Pagination envelope used by every list endpoint. */
export interface Paginated<T> {
  items: T[]
  page: number
  page_size: number
  total: number
  pages: number
}

export type { components }
