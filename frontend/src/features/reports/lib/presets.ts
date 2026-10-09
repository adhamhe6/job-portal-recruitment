import { subDays } from 'date-fns'
import { dates } from '@/lib/format'

export interface DatePreset {
  id: string
  label: string
  range: () => { from: string; to: string }
}

/** Quick ranges for the filter bar. Dates are calendar days (the API treats them as UTC days). */
export const DATE_PRESETS: DatePreset[] = [
  {
    id: '30',
    label: 'Last 30 days',
    range: () => ({ from: dates.isoDate(subDays(new Date(), 29)), to: dates.isoDate() }),
  },
  {
    id: '90',
    label: 'Last 90 days',
    range: () => ({ from: dates.isoDate(subDays(new Date(), 89)), to: dates.isoDate() }),
  },
  {
    id: 'year',
    label: 'This year',
    range: () => ({ from: `${new Date().getFullYear()}-01-01`, to: dates.isoDate() }),
  },
  { id: 'all', label: 'All time', range: () => ({ from: '', to: '' }) },
]

/** Which preset (if any) matches the current range, for pressed-state styling. */
export function activePreset(from: string, to: string): string | null {
  for (const p of DATE_PRESETS) {
    const r = p.range()
    if (r.from === from && r.to === to) return p.id
  }
  return null
}
