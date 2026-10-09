import { Archive, CirclePause, CirclePlay, Rocket, XCircle, type LucideIcon } from 'lucide-react'
import type { JobStatus } from '@/lib/api'

export type LifecycleAction = 'publish' | 'pause' | 'resume' | 'close' | 'archive'

/** Mirrors the backend state machine (services/jobs.py::JOB_TRANSITIONS). Staff detail responses also carry `allowed_transitions`. */
export const JOB_TRANSITIONS: Record<JobStatus, JobStatus[]> = {
  DRAFT: ['PUBLISHED', 'ARCHIVED'],
  PUBLISHED: ['PAUSED', 'CLOSED'],
  PAUSED: ['PUBLISHED', 'CLOSED'],
  CLOSED: ['ARCHIVED'],
  ARCHIVED: [],
}

/** Statuses a job can still be edited in (backend: JOB_NOT_EDITABLE otherwise). */
export const EDITABLE_STATUSES: JobStatus[] = ['DRAFT', 'PUBLISHED', 'PAUSED']

export interface ActionDef {
  action: LifecycleAction
  label: string
  icon: LucideIcon
  destructive?: boolean
  /** Offer an optional reason field in the confirmation. */
  askReason?: boolean
  confirmLabel: string
  title: (jobTitle: string) => string
  description: string
  success: string
}

export const ACTIONS: Record<LifecycleAction, ActionDef> = {
  publish: {
    action: 'publish',
    label: 'Publish',
    icon: Rocket,
    confirmLabel: 'Publish job',
    title: (t) => `Publish “${t}”?`,
    description:
      'The job becomes visible to candidates and starts accepting applications. Candidate matching runs in the background and recruiters are notified when it completes.',
    success: 'Job published',
  },
  pause: {
    action: 'pause',
    label: 'Pause',
    icon: CirclePause,
    askReason: true,
    confirmLabel: 'Pause job',
    title: (t) => `Pause “${t}”?`,
    description:
      'The job is hidden from search and stops accepting applications until you resume it. Existing applications are kept.',
    success: 'Job paused',
  },
  resume: {
    action: 'resume',
    label: 'Resume',
    icon: CirclePlay,
    confirmLabel: 'Resume job',
    title: (t) => `Resume “${t}”?`,
    description: 'The job becomes visible again and accepts applications.',
    success: 'Job resumed',
  },
  close: {
    action: 'close',
    label: 'Close',
    icon: XCircle,
    destructive: true,
    askReason: true,
    confirmLabel: 'Close job',
    title: (t) => `Close “${t}”?`,
    description:
      'Closing ends the hiring round: the job leaves search and no new applications are accepted. You can archive it afterwards. Closed jobs cannot be reopened.',
    success: 'Job closed',
  },
  archive: {
    action: 'archive',
    label: 'Archive',
    icon: Archive,
    destructive: true,
    askReason: true,
    confirmLabel: 'Archive job',
    title: (t) => `Archive “${t}”?`,
    description: 'Archived jobs are kept for reporting but are read-only and cannot be reopened.',
    success: 'Job archived',
  },
}

/** Map (current status, target status) -> the action that performs it. */
export function actionFor(from: JobStatus, to: JobStatus): LifecycleAction | null {
  switch (to) {
    case 'PUBLISHED':
      return from === 'PAUSED' ? 'resume' : 'publish'
    case 'PAUSED':
      return 'pause'
    case 'CLOSED':
      return 'close'
    case 'ARCHIVED':
      return 'archive'
    default:
      return null
  }
}

const ORDER: LifecycleAction[] = ['publish', 'resume', 'pause', 'close', 'archive']

/** Actions to offer for a job; `allowed` (from the API) wins over the local table when present. */
export function availableActions(status: JobStatus, allowed?: JobStatus[]): LifecycleAction[] {
  const targets = allowed ?? JOB_TRANSITIONS[status]
  const actions = targets.map((t) => actionFor(status, t)).filter((a): a is LifecycleAction => a !== null)
  return ORDER.filter((a) => actions.includes(a))
}
