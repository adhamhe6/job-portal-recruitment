import type { CompanyOut, MemberOut } from '@/lib/api'
import type {
  AdminDashboardData,
  AdminTask,
  AdminUser,
  AuditEvent,
  EmbeddingsStatus,
  MatchingStatus,
  SystemStatus,
} from '../api/types'

export const makeAdminUser = (o: Partial<AdminUser> = {}): AdminUser => ({
  id: 'u-1',
  email: 'jo.candidate@example.com',
  first_name: 'Jo',
  last_name: 'Candidate',
  phone: null,
  role: 'CANDIDATE',
  status: 'ACTIVE',
  company_id: null,
  last_login_at: '2026-10-08T10:00:00Z',
  created_at: '2026-09-01T00:00:00Z',
  ...o,
})

export const makeCompany = (o: Partial<CompanyOut> = {}): CompanyOut => ({
  id: 'c-1',
  name: 'Northwind Labs',
  slug: 'northwind-labs',
  description: 'Developer tooling.',
  industry: 'Software',
  website: 'https://northwind.example.com',
  location: 'Berlin, Germany',
  size: '51-200',
  logo_url: null,
  status: 'ACTIVE',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-02-01T00:00:00Z',
  ...o,
})

export const makeMember = (o: Partial<MemberOut> = {}): MemberOut => ({
  id: 'm-1',
  email: 'riley@northwind.example.com',
  first_name: 'Riley',
  last_name: 'Recruiter',
  role: 'RECRUITER',
  status: 'ACTIVE',
  job_title: 'Head of Talent',
  department: 'People',
  is_company_admin: false,
  last_login_at: '2026-10-08T10:00:00Z',
  ...o,
})

export const makeSystem = (o: Partial<SystemStatus> = {}): SystemStatus => ({
  status: 'ok',
  checked_at: new Date().toISOString(),
  app: {
    name: 'TalentLens',
    version: '1.0.0',
    environment: 'production',
    python_version: '3.12.1',
    job_backend: 'arq',
    cache_enabled: true,
  },
  database: {
    ok: true,
    latency_ms: 0.5,
    pgvector_version: '0.8.0',
    migration_revision: '0001',
    migration_head: '0001',
    migrations_current: true,
    error: null,
  },
  redis: { ok: true, latency_ms: 0.4, queue_depth: 2, error: null },
  embedding: {
    backend: 'wordllama',
    model_name: 'wordllama-l2',
    model_version: 'v1',
    dimension: 256,
    loaded: true,
    error: null,
  },
  worker: {
    mode: 'arq',
    alive: true,
    health_key: 'arq:queue:health-check',
    health_ttl_seconds: 20,
    last_check: 'j_complete=1 j_failed=0',
    jobs_complete: 12,
    jobs_failed: 0,
    jobs_retried: 0,
    jobs_ongoing: 0,
    queued: 0,
  },
  tasks: {
    by_status: { PENDING: 0, RUNNING: 0, COMPLETED: 10, FAILED: 0 },
    last_24h_by_status: { PENDING: 0, RUNNING: 0, COMPLETED: 10, FAILED: 0 },
    stale_pending_after_minutes: 10,
    stale_running_after_minutes: 30,
    stale_count: 0,
    stale: [],
  },
  ...o,
})

export const makeTask = (o: Partial<AdminTask> = {}): AdminTask => ({
  id: 'abcdef12-0000-0000-0000-000000000001',
  type: 'MATCH_JOB',
  status: 'COMPLETED',
  progress: 100,
  stage: 'done',
  attempts: 1,
  error_code: null,
  error_message: null,
  dedupe_key: null,
  created_by_id: null,
  company_id: null,
  has_result: true,
  created_at: '2026-10-09T10:00:00Z',
  updated_at: '2026-10-09T10:00:05Z',
  started_at: '2026-10-09T10:00:01Z',
  finished_at: '2026-10-09T10:00:05Z',
  ...o,
})

export const makeAudit = (o: Partial<AuditEvent> = {}): AuditEvent => ({
  id: 'a-1',
  action: 'job.created',
  entity_type: 'job',
  entity_id: '11111111-2222-3333-4444-555555555555',
  actor_id: 'u-2',
  actor_name: 'Riley Recruiter',
  actor_email: 'recruiter@demo.example',
  company_id: 'c-1',
  metadata: { status: 'DRAFT' },
  created_at: '2026-10-09T09:00:00Z',
  ...o,
})

const bucket = (population: string, o: Partial<EmbeddingsStatus['jobs']> = {}) => ({
  population,
  total: 10,
  current: 10,
  outdated: 0,
  missing: 0,
  ...o,
})

export const makeEmbeddings = (o: Partial<EmbeddingsStatus> = {}): EmbeddingsStatus => ({
  model_name: 'wordllama-l2',
  model_version: 'v1',
  dimension: 256,
  jobs: bucket('jobs that are PUBLISHED or PAUSED'),
  candidates: bucket('all candidate profiles'),
  resume_results: bucket('processed résumés', { total: 0, current: 0 }),
  active_refresh_task_id: null,
  last_refresh: null,
  ...o,
})

export const makeMatching = (o: Partial<MatchingStatus> = {}): MatchingStatus => ({
  matching_version: 'v1',
  embedding_model: 'wordllama-l2',
  embedding_version: 'v1',
  pairs: 205,
  jobs_with_matches: 10,
  candidates_with_matches: 16,
  last_generated_at: '2026-10-09T08:00:00Z',
  stale_by_version: 0,
  by_version: [
    { matching_version: 'v1', embedding_model: 'wordllama-l2', embedding_version: 'v1', pairs: 205, current: true },
  ],
  published_jobs: 10,
  published_jobs_without_matches: 0,
  tasks: { active: 0, last_24h_by_status: { PENDING: 0, RUNNING: 0, COMPLETED: 10, FAILED: 0 } },
  ...o,
})

export const makeDashboard = (o: Partial<AdminDashboardData> = {}): AdminDashboardData => ({
  generated_at: new Date().toISOString(),
  users_total: 25,
  users_by_role: { ADMIN: 2, RECRUITER: 5, HIRING_MANAGER: 1, CANDIDATE: 17 },
  users_by_status: { ACTIVE: 24, SUSPENDED: 1 },
  companies: { total: 4, active: 3, suspended: 1 },
  jobs_by_status: { DRAFT: 1, PUBLISHED: 10, PAUSED: 1, CLOSED: 1, ARCHIVED: 1 },
  applications_by_status: { APPLIED: 5, SCREENING: 4, SHORTLISTED: 4, INTERVIEW: 2, OFFER: 1, HIRED: 2, REJECTED: 1, WITHDRAWN: 1 },
  interviews_by_status: {},
  resumes_by_status: {},
  tasks_last_24h_by_status: { PENDING: 0, RUNNING: 0, COMPLETED: 10, FAILED: 0 },
  signups_over_time: [
    { bucket: '2026-10-07', count: 0 },
    { bucket: '2026-10-08', count: 3 },
    { bucket: '2026-10-09', count: 5 },
  ],
  recent_audit_events: [
    {
      id: 'ev-1',
      action: 'job.archived',
      entity_type: 'job',
      entity_id: 'j-1',
      actor_id: 'u-2',
      actor_name: 'Riley Recruiter',
      company_id: 'c-1',
      created_at: new Date(Date.now() - 3_600_000).toISOString(),
    },
  ],
  matches: { pairs: 205, jobs_with_matches: 10, candidates_with_matches: 16, last_generated_at: '2026-10-09T08:00:00Z' },
  ...o,
})
