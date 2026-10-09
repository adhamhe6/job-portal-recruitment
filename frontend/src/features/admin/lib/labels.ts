import type { Role } from '@/lib/api'
import { fmt } from '@/lib/format'
import type { TaskStatus, TaskType } from '../api/types'

export const STAFF_ROLES: readonly Role[] = ['RECRUITER', 'HIRING_MANAGER']
export const isStaffRole = (r: string): boolean => (STAFF_ROLES as readonly string[]).includes(r)

export const ACCOUNT_STATUS_LABELS = { ACTIVE: 'Active', SUSPENDED: 'Suspended' } as const
export const ACCOUNT_STATUS_OPTIONS = [
  { value: 'ACTIVE', label: 'Active' },
  { value: 'SUSPENDED', label: 'Suspended' },
]

export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  PROCESS_RESUME: 'Résumé processing',
  MATCH_JOB: 'Match a job',
  MATCH_CANDIDATE: 'Match a candidate',
  REFRESH_EMBEDDINGS: 'Re-embed stale items',
  BULK_RESUME_IMPORT: 'Bulk résumé import',
  EXPORT_REPORT: 'Report export',
}
export const TASK_TYPE_OPTIONS = (Object.entries(TASK_TYPE_LABELS) as [TaskType, string][]).map(
  ([value, label]) => ({ value, label }),
)

export const TASK_STATUS_ORDER: TaskStatus[] = ['PENDING', 'RUNNING', 'COMPLETED', 'FAILED']
export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  PENDING: 'Pending',
  RUNNING: 'Running',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
}
export const TASK_STATUS_OPTIONS = TASK_STATUS_ORDER.map((value) => ({
  value,
  label: TASK_STATUS_LABELS[value],
}))

export const taskTypeLabel = (t: string): string => TASK_TYPE_LABELS[t as TaskType] ?? fmt.label(t)

/** Entity types that appear in the audit log (backend `record_audit(entity_type=…)`). */
export const AUDIT_ENTITY_OPTIONS = [
  'application',
  'company',
  'interview',
  'job',
  'resume',
  'task',
  'user',
].map((v) => ({ value: v, label: fmt.label(v) }))

const ACTION_LABELS: Record<string, string> = {
  'user.registered': 'User registered',
  'user.created': 'User created by an administrator',
  'user.updated': 'User updated',
  'user.password_changed': 'Password changed',
  'member.updated': 'Team member updated',
  'company.created': 'Company created',
  'company.updated': 'Company updated',
  'embeddings.refresh_requested': 'Re-embedding requested',
  'task.retried': 'Background task retried',
}

/** "job.status_changed" -> "Job status changed" (known actions have curated wording). */
export function describeAction(action: string): string {
  return ACTION_LABELS[action] ?? fmt.label(action.replace('.', ' '))
}

/** Compact "a: b · c: d" rendering of audit metadata (primitive values only, length-capped; never raw JSON). */
export function summarizeMetadata(meta: Record<string, unknown> | null | undefined, max = 120): string {
  if (!meta) return ''
  const parts: string[] = []
  for (const [k, v] of Object.entries(meta)) {
    if (v === null || v === undefined || typeof v === 'object') continue
    parts.push(`${k.replace(/_/g, ' ')}: ${String(v)}`)
  }
  const s = parts.join(' · ')
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

/** Cap messages that come from background tasks so a stack-trace-sized message cannot wreck the layout. */
export function safeMessage(msg: string | null | undefined, max = 200): string {
  if (!msg) return ''
  const one = msg.replace(/\s+/g, ' ').trim()
  return one.length > max ? `${one.slice(0, max - 1)}…` : one
}
