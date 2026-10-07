/** Permission names returned by GET /auth/me (`permissions`). Mirrors backend `core/security.py::Permission`. */
export const PERMISSIONS = [
  'manage_users',
  'manage_companies',
  'manage_own_company',
  'create_skill',
  'manage_skills',
  'manage_jobs',
  'view_company_jobs',
  'search_candidates',
  'view_candidates',
  'manage_applications',
  'review_applications',
  'manage_own_profile',
  'apply_to_jobs',
  'upload_resume',
  'import_resumes',
  'schedule_interviews',
  'view_interviews',
  'provide_feedback',
  'view_matches',
  'run_matching',
  'view_recommendations',
  'view_reports',
  'view_admin_reports',
  'monitor_system',
] as const

export type Permission = (typeof PERMISSIONS)[number]
