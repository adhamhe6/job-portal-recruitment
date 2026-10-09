import { format, parseISO } from 'date-fns'
import type { InterviewType } from '../api/interviews'

export const INTERVIEW_TYPE_LABELS: Record<InterviewType, string> = {
  PHONE_SCREEN: 'Phone screen',
  TECHNICAL: 'Technical interview',
  BEHAVIORAL: 'Behavioural interview',
  PANEL: 'Panel interview',
  ONSITE: 'On-site interview',
  FINAL: 'Final interview',
}

/** "9:00 AM" in the browser's timezone. */
export const timeOfDay = (iso: string) => format(parseISO(iso), 'h:mm a')
/** "Thu, Oct 15, 2026" in the browser's timezone. */
export const longDate = (iso: string) => format(parseISO(iso), 'EEE, MMM d, yyyy')

/** "09:00" taken from an ISO string that already carries the interview's local wall-clock time. */
export const wallClock = (local: string) => local.slice(11, 16)

/** Browser timezone name, e.g. "Europe/Berlin" (falls back to "your local time"). */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'your local time'
  } catch {
    return 'your local time'
  }
}

/** Short label for the time zone offset difference note (only shown when the interview zone differs from the browser's). */
export const sameZone = (zone: string) =>
  zone === browserTimeZone() || (zone === 'UTC' && browserTimeZone() === 'UTC')
