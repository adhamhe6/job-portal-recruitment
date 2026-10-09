import type { StaffInterviewItem } from '../api/types'
import { dayKey, formatDay } from './time'

export interface AgendaDay {
  /** `yyyy-MM-dd` in the viewer's timezone */
  key: string
  /** "Today · Fri, Oct 9, 2026" */
  heading: string
  items: StaffInterviewItem[]
}

function shift(key: string, days: number): string {
  const [y, m, d] = key.split('-').map(Number)
  return new Date(Date.UTC(y!, m! - 1, d! + days)).toISOString().slice(0, 10)
}

/**
 * Group interviews by the calendar day they start on in the viewer's timezone. Day order follows the order of the
 * input (the API sorts by start), so ascending and descending lists both read naturally.
 */
export function groupByDay(
  items: readonly StaffInterviewItem[],
  viewerTz: string,
  now: Date = new Date(),
): AgendaDay[] {
  const today = dayKey(now.toISOString(), viewerTz)
  const tomorrow = shift(today, 1)
  const yesterday = shift(today, -1)
  const days = new Map<string, AgendaDay>()
  for (const iv of items) {
    const key = dayKey(iv.start_at, viewerTz)
    let day = days.get(key)
    if (!day) {
      const label = formatDay(iv.start_at, viewerTz)
      const prefix = key === today ? 'Today · ' : key === tomorrow ? 'Tomorrow · ' : key === yesterday ? 'Yesterday · ' : ''
      day = { key, heading: `${prefix}${label}`, items: [] }
      days.set(key, day)
    }
    day.items.push(iv)
  }
  return [...days.values()]
}
