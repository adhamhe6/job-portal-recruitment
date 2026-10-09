import type { components } from '@/lib/api'

/**
 * Admin / monitoring response shapes.
 *
 * `src/lib/api/schema.d.ts` predates the admin endpoints (`/admin/*`, `/reports/admin-dashboard`), so the minimal
 * shapes are declared here, mirroring `backend/app/schemas/admin.py` and `schemas/report.py`. Once `npm run gen:api`
 * is re-run these can be replaced with aliases of the generated schema.
 */
type S = components['schemas']

export type TaskStatus = S['TaskStatus']
export type TaskType = S['TaskType']

export type AdminUser = S['UserOut']
export type AdminUserCreate = S['AdminUserCreate']
export type AdminUserUpdate = S['AdminUserUpdate']
export type AdminCompany = S['CompanyOut']
export type AdminCompanyCreate = S['CompanyCreate']
export type AdminCompanyUpdate = S['CompanyUpdate']

export interface DatabaseStatus {
  ok: boolean
  latency_ms: number | null
  pgvector_version: string | null
  migration_revision: string | null
  migration_head: string | null
  migrations_current: boolean | null
  error: string | null
}

export interface RedisStatus {
  ok: boolean
  latency_ms: number | null
  queue_depth: number | null
  error: string | null
}

export interface EmbeddingModelStatus {
  backend: string
  model_name: string
  model_version: string
  dimension: number
  loaded: boolean
  error: string | null
}

export interface WorkerStatus {
  mode: string
  alive: boolean | null
  health_key: string
  health_ttl_seconds: number | null
  last_check: string | null
  jobs_complete: number | null
  jobs_failed: number | null
  jobs_retried: number | null
  jobs_ongoing: number | null
  queued: number | null
}

export interface StaleTask {
  id: string
  type: TaskType
  status: TaskStatus
  stage: string | null
  created_at: string
  updated_at: string
  age_minutes: number
  worker_heartbeat: boolean | null
}

export interface TaskHealth {
  by_status: Record<string, number>
  last_24h_by_status: Record<string, number>
  stale_pending_after_minutes: number
  stale_running_after_minutes: number
  stale_count: number
  stale: StaleTask[]
}

export interface SystemStatus {
  status: 'ok' | 'degraded' | 'down'
  checked_at: string
  app: {
    name: string
    version: string
    environment: string
    python_version: string
    job_backend: string
    cache_enabled: boolean
  }
  database: DatabaseStatus
  redis: RedisStatus
  embedding: EmbeddingModelStatus
  worker: WorkerStatus
  tasks: TaskHealth
}

export interface AdminTask {
  id: string
  type: TaskType
  status: TaskStatus
  progress: number
  stage: string | null
  attempts: number
  error_code: string | null
  error_message: string | null
  dedupe_key: string | null
  created_by_id: string | null
  company_id: string | null
  has_result: boolean
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
}

export interface AuditEvent {
  id: string
  action: string
  entity_type: string
  entity_id: string | null
  actor_id: string | null
  actor_name: string | null
  actor_email: string | null
  company_id: string | null
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface EmbeddingBucket {
  population: string
  total: number
  current: number
  outdated: number
  missing: number
}

export interface EmbeddingsStatus {
  model_name: string
  model_version: string
  dimension: number
  jobs: EmbeddingBucket
  candidates: EmbeddingBucket
  resume_results: EmbeddingBucket
  active_refresh_task_id: string | null
  last_refresh: {
    task_id: string
    status: TaskStatus
    finished_at: string | null
    result: Record<string, unknown> | null
  } | null
}

export interface EmbeddingRefresh {
  task_id: string
  status: TaskStatus
  created: boolean
}

export interface MatchingStatus {
  matching_version: string
  embedding_model: string
  embedding_version: string
  pairs: number
  jobs_with_matches: number
  candidates_with_matches: number
  last_generated_at: string | null
  stale_by_version: number
  by_version: {
    matching_version: string
    embedding_model: string
    embedding_version: string
    pairs: number
    current: boolean
  }[]
  published_jobs: number
  published_jobs_without_matches: number
  tasks: { active: number; last_24h_by_status: Record<string, number> }
}

export interface AdminDashboardData {
  generated_at: string
  users_total: number
  users_by_role: Record<string, number>
  users_by_status: Record<string, number>
  companies: { total: number; active: number; suspended: number }
  jobs_by_status: Record<string, number>
  applications_by_status: Record<string, number>
  interviews_by_status: Record<string, number>
  resumes_by_status: Record<string, number>
  tasks_last_24h_by_status: Record<string, number>
  signups_over_time: { bucket: string; count: number }[]
  recent_audit_events: {
    id: string
    action: string
    entity_type: string
    entity_id: string | null
    actor_id: string | null
    actor_name: string | null
    company_id: string | null
    created_at: string
  }[]
  matches: {
    pairs: number
    jobs_with_matches: number
    candidates_with_matches: number
    last_generated_at: string | null
  }
}
