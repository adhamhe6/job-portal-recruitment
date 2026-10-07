import type { JobDetail, JobListItem, JobPublic, Me, NotificationOut, Paginated, Role, SkillOut, TokenResponse } from '@/lib/api'

/** Typed factories for API payloads. Defaults are valid; override what a test cares about. */

let seq = 0
export const uid = (prefix = 'id') => `${prefix}-${++seq}`

const PERMISSIONS: Record<Role, string[]> = {
  CANDIDATE: ['apply_to_jobs', 'create_skill', 'manage_own_profile', 'upload_resume', 'view_interviews', 'view_recommendations'],
  RECRUITER: [
    'manage_own_company', 'create_skill', 'manage_jobs', 'view_company_jobs', 'search_candidates', 'view_candidates',
    'manage_applications', 'review_applications', 'import_resumes', 'schedule_interviews', 'view_interviews',
    'provide_feedback', 'view_matches', 'run_matching', 'view_reports',
  ],
  HIRING_MANAGER: ['view_company_jobs', 'view_candidates', 'review_applications', 'view_interviews', 'provide_feedback', 'view_matches', 'view_reports'],
  ADMIN: [
    'manage_users', 'manage_companies', 'manage_own_company', 'create_skill', 'manage_skills', 'manage_jobs', 'view_company_jobs',
    'search_candidates', 'view_candidates', 'manage_applications', 'review_applications', 'manage_own_profile', 'apply_to_jobs',
    'upload_resume', 'import_resumes', 'schedule_interviews', 'view_interviews', 'provide_feedback', 'view_matches', 'run_matching',
    'view_recommendations', 'view_reports', 'view_admin_reports', 'monitor_system',
  ],
}

export const COMPANY_ID = '99be659f-45f3-4d5e-a592-8603d96f0259'

export function makeUser(role: Role = 'CANDIDATE', overrides: Partial<Me> = {}): Me {
  const staff = role === 'RECRUITER' || role === 'HIRING_MANAGER'
  return {
    id: `user-${role.toLowerCase()}`,
    email: `${role.toLowerCase()}@demo.example`,
    first_name: role === 'CANDIDATE' ? 'Alex' : 'Riley',
    last_name: role === 'CANDIDATE' ? 'Rivera' : 'Recruiter',
    phone: null,
    role,
    status: 'ACTIVE',
    company_id: staff ? COMPANY_ID : null,
    last_login_at: null,
    created_at: '2026-01-01T00:00:00Z',
    company: staff ? { id: COMPANY_ID, name: 'Northwind Labs', slug: 'northwind-labs', logo_url: null } : null,
    candidate_id: role === 'CANDIDATE' ? 'cand-1' : null,
    is_company_admin: role === 'RECRUITER',
    permissions: PERMISSIONS[role],
    ...overrides,
  }
}

export const tokenFor = (user: Me, token = 'access-token-1'): TokenResponse => ({
  access_token: token,
  token_type: 'bearer',
  expires_in: 900,
  user,
})

export function makeJobListItem(overrides: Partial<JobListItem> = {}): JobListItem {
  const id = overrides.id ?? uid('job')
  return {
    id,
    title: 'Senior Backend Engineer',
    company_id: COMPANY_ID,
    company_name: 'Northwind Labs',
    company_logo_url: null,
    department: 'Platform',
    location: 'Berlin, Germany',
    employment_type: 'FULL_TIME',
    workplace_type: 'HYBRID',
    experience_level: 'SENIOR',
    min_experience_years: '4.0',
    salary_min: '90000.00',
    salary_max: '120000.00',
    salary_currency: 'EUR',
    skills: ['Python', 'PostgreSQL', 'Redis'],
    status: 'PUBLISHED',
    published_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
    application_deadline: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    is_saved: null,
    has_applied: null,
    match_score: null,
    application_count: null,
    ...overrides,
  }
}

const company = {
  id: COMPANY_ID,
  name: 'Northwind Labs',
  slug: 'northwind-labs',
  description: 'Developer tooling.',
  industry: 'Software',
  website: 'https://northwind.example.com',
  location: 'Berlin, Germany',
  size: '51-200' as const,
  logo_url: null,
}

export const skill = (name: string, id = `skill-${name.toLowerCase()}`): SkillOut => ({ id, name, category: 'Languages', family: null, is_verified: true })

export function makeJobPublic(overrides: Partial<JobPublic> = {}): JobPublic {
  return {
    id: 'job-1',
    title: 'Senior Backend Engineer',
    department: 'Platform',
    description: 'Build and operate high-throughput services for our developer products.',
    responsibilities: 'Design APIs.\n\n- Review code\n- Mentor engineers',
    qualifications: '4+ years of backend development.',
    benefits: 'Learning budget.',
    location: 'Berlin, Germany',
    employment_type: 'FULL_TIME',
    workplace_type: 'HYBRID',
    salary_min: '90000.00',
    salary_max: '120000.00',
    salary_currency: 'EUR',
    min_experience_years: '4.0',
    max_experience_years: null,
    experience_level: 'SENIOR',
    min_education_level: 'BACHELOR',
    application_deadline: null,
    status: 'PUBLISHED',
    published_at: '2026-09-16T00:00:00Z',
    created_at: '2026-09-14T00:00:00Z',
    updated_at: '2026-09-16T00:00:00Z',
    company,
    skills: [
      { skill: skill('Python'), requirement: 'REQUIRED', min_years: null },
      { skill: skill('PostgreSQL'), requirement: 'REQUIRED', min_years: '3.0' },
      { skill: skill('Kubernetes'), requirement: 'PREFERRED', min_years: null },
    ],
    is_saved: null,
    my_application_id: null,
    my_application_status: null,
    match: null,
    can_apply: true,
    apply_blocked_reason: null,
    ...overrides,
  }
}

export function makeJobDetail(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    ...makeJobPublic(),
    company_id: COMPANY_ID,
    created_by_id: 'user-recruiter',
    hiring_manager_id: null,
    hiring_manager_name: null,
    closed_at: null,
    application_count: 3,
    embedding_ready: true,
    allowed_transitions: ['CLOSED', 'PAUSED'],
    ...overrides,
  }
}

export function page<T>(items: T[], overrides: Partial<Paginated<T>> = {}): Paginated<T> {
  return { items, page: 1, page_size: 10, total: items.length, pages: items.length ? 1 : 0, ...overrides }
}

export function makeNotification(overrides: Partial<NotificationOut> = {}): NotificationOut {
  return {
    id: uid('n'),
    type: 'APPLICATION_STATUS_CHANGED',
    title: 'Application update',
    message: 'Your application was shortlisted.',
    is_read: false,
    read_at: null,
    job_id: 'job-1',
    application_id: 'app-1',
    interview_id: null,
    resume_id: null,
    created_at: new Date(Date.now() - 600_000).toISOString(),
    ...overrides,
  }
}

export const errorBody = (code: string, message: string, details: unknown = null) => ({ error: { code, message, details, request_id: 'req-test' } })
