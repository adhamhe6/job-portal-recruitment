import { paths } from '@/routes/paths'
import type { NotificationOut } from '@/lib/api'

/**
 * Where a notification should take the user. The backend gives us entity ids (interview > application > job > résumé);
 * the notification type refines it (a new candidate match for a recruiter belongs on the matching page).
 */
export function notificationHref(n: Pick<NotificationOut, 'type' | 'job_id' | 'application_id' | 'interview_id' | 'resume_id'>): string | null {
  switch (n.type) {
    case 'INTERVIEW_SCHEDULED':
    case 'INTERVIEW_RESCHEDULED':
    case 'INTERVIEW_CANCELLED':
      if (n.interview_id) return paths.interview(n.interview_id)
      break
    case 'NEW_CANDIDATE_MATCH':
      if (n.job_id) return paths.matchingJob(n.job_id)
      break
    case 'NEW_JOB_RECOMMENDATION':
      if (n.job_id) return paths.job(n.job_id)
      break
    case 'RESUME_PROCESSED':
    case 'RESUME_FAILED':
      return paths.resume
    case 'BULK_IMPORT_COMPLETED':
      return paths.candidates
    default:
      break
  }
  if (n.interview_id) return paths.interview(n.interview_id)
  if (n.application_id) return paths.application(n.application_id)
  if (n.job_id) return paths.job(n.job_id)
  if (n.resume_id) return paths.resume
  return null
}
