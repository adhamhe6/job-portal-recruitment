/**
 * Single source of truth for URLs. Use these helpers for every <Link>/navigate() so a route move is a one-line change.
 * The route table (routes/index.tsx) maps each of these to a lazily loaded page module.
 */
export const paths = {
  home: '/',
  login: '/login',
  register: '/register',
  registerEmployer: '/register/employer',

  // Jobs (public search + detail, adaptive layout)
  jobs: '/jobs',
  jobsSaved: '/jobs/saved',
  job: (id: string) => `/jobs/${id}`,

  // Signed-in area
  dashboard: '/dashboard',
  recommended: '/recommended',
  applications: '/applications',
  application: (id: string) => `/applications/${id}`,
  interviews: '/interviews',
  interview: (id: string) => `/interviews/${id}`,
  resume: '/resume',
  profile: '/profile',
  notifications: '/notifications',

  // Staff
  manageJobs: '/manage/jobs',
  manageJobNew: '/manage/jobs/new',
  manageJobEdit: (id: string) => `/manage/jobs/${id}/edit`,
  candidates: '/candidates',
  candidate: (id: string) => `/candidates/${id}`,
  matching: '/matching',
  matchingJob: (jobId: string) => `/matching/${jobId}`,
  reports: '/reports',

  // Settings
  settings: '/settings',
  settingsCompany: '/settings/company',
  settingsTeam: '/settings/team',

  // Admin
  adminUsers: '/admin/users',
  adminCompanies: '/admin/companies',
  adminSystem: '/admin/system',
} as const

/** Route patterns (react-router syntax) for the few that take params. */
export const patterns = {
  job: '/jobs/:id',
  application: '/applications/:id',
  interview: '/interviews/:id',
  manageJobEdit: '/manage/jobs/:id/edit',
  candidate: '/candidates/:id',
  matchingJob: '/matching/:jobId',
} as const

/** Build `/login?next=<path>` so a login returns the user where they were heading. */
export function loginUrl(next?: string): string {
  return next && next !== '/' ? `${paths.login}?next=${encodeURIComponent(next)}` : paths.login
}
