import { ApiError, errorMessage } from '@/lib/api'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import type { ApplicationStatus } from '@/lib/api'

const label = (s: unknown) =>
  typeof s === 'string' ? (APPLICATION_STATUS_LABELS[s as ApplicationStatus] ?? s) : null

/** Plain-language explanation for a failed stage change / withdrawal. */
export function describeStageError(error: unknown): { title: string; message: string } {
  if (error instanceof ApiError) {
    if (error.code === 'INVALID_STATE_TRANSITION') {
      const d = (error.details ?? {}) as { from?: unknown; to?: unknown }
      const from = label(d.from)
      const to = label(d.to)
      return {
        title: "That move isn't possible",
        message:
          from && to
            ? `The application is ${from.toLowerCase()}, so it cannot move to ${to.toLowerCase()}. Someone may have just changed it — the list has been refreshed.`
            : error.message,
      }
    }
    if (error.code === 'CANNOT_WITHDRAW') {
      return {
        title: "This application can't be withdrawn",
        message:
          'It is already past the screening stage. Please contact the recruiter if you want to withdraw.',
      }
    }
    if (error.status === 403 || error.status === 404) {
      return {
        title: 'Access lost',
        message: 'You no longer have access to this application, or it has been removed.',
      }
    }
  }
  return { title: "Couldn't update the application", message: errorMessage(error) }
}
