import { differenceInCalendarDays, format, formatDistanceToNowStrict, isValid, parseISO } from 'date-fns'

/** Money / number / date formatting. All user-facing formatting goes through here (Intl + date-fns). */

type Numeric = number | string | null | undefined

function toNumber(v: Numeric): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}

const intFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const numFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })

const currencyCache = new Map<string, Intl.NumberFormat>()
function currencyFormatter(currency: string, compact: boolean): Intl.NumberFormat {
  const key = `${currency}:${compact}`
  let f = currencyCache.get(key)
  if (!f) {
    try {
      f = new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency,
        notation: compact ? 'compact' : 'standard',
        maximumFractionDigits: compact ? 1 : 0,
      })
    } catch {
      // Unknown currency code: fall back to a plain number with the code as prefix.
      f = new Intl.NumberFormat('en-US', {
        maximumFractionDigits: compact ? 1 : 0,
        notation: compact ? 'compact' : 'standard',
      })
    }
    currencyCache.set(key, f)
  }
  return f
}

export const fmt = {
  int: (v: Numeric) => {
    const n = toNumber(v)
    return n === null ? '—' : intFmt.format(n)
  },
  num: (v: Numeric) => {
    const n = toNumber(v)
    return n === null ? '—' : numFmt.format(n)
  },
  /** 0.82 -> "82%" */
  percent: (v: Numeric, digits = 0) => {
    const n = toNumber(v)
    return n === null ? '—' : `${(n * 100).toFixed(digits)}%`
  },
  money: (v: Numeric, currency = 'USD', compact = false) => {
    const n = toNumber(v)
    return n === null ? '—' : currencyFormatter(currency, compact).format(n)
  },
  /** "Berlin, Germany" style enum label: FULL_TIME -> "Full time". */
  label: (v: string | null | undefined) =>
    v
      ? v
          .toLowerCase()
          .replace(/_/g, ' ')
          .replace(/^\w/, (c) => c.toUpperCase())
      : '—',
}

/** Salary range with the job's own currency: "€80K – €105K", "From €50K", "Up to €90K" or null. */
export function formatSalaryRange(
  min: Numeric,
  max: Numeric,
  currency = 'USD',
  compact = true,
): string | null {
  const lo = toNumber(min)
  const hi = toNumber(max)
  if (lo === null && hi === null) return null
  const f = (n: number) => fmt.money(n, currency, compact)
  if (lo !== null && hi !== null) return lo === hi ? f(lo) : `${f(lo)} – ${f(hi)}`
  if (lo !== null) return `From ${f(lo)}`
  return `Up to ${f(hi as number)}`
}

/** Years of experience: "3+ yrs", "3–5 yrs", "No experience required". */
export function formatExperienceRange(min: Numeric, max: Numeric): string {
  const lo = toNumber(min) ?? 0
  const hi = toNumber(max)
  if (hi !== null && hi > lo) return `${fmt.num(lo)}–${fmt.num(hi)} yrs`
  if (lo === 0) return 'No experience required'
  return `${fmt.num(lo)}+ yrs`
}

function toDate(v: string | Date | null | undefined): Date | null {
  if (!v) return null
  const d = v instanceof Date ? v : parseISO(v) // date-only strings parse as local dates, timestamps as instants
  return isValid(d) ? d : null
}

export const dates = {
  /** "Oct 7, 2026" */
  date: (v: string | Date | null | undefined) => {
    const d = toDate(v)
    return d ? format(d, 'MMM d, yyyy') : '—'
  },
  /** "Oct 7, 2026, 3:30 PM" */
  dateTime: (v: string | Date | null | undefined) => {
    const d = toDate(v)
    return d ? format(d, 'MMM d, yyyy, h:mm a') : '—'
  },
  /** "3 days ago" / "in 2 hours" */
  relative: (v: string | Date | null | undefined) => {
    const d = toDate(v)
    if (!d) return '—'
    const diff = Math.abs(Date.now() - d.getTime())
    if (diff < 45_000) return 'just now'
    return formatDistanceToNowStrict(d, { addSuffix: true })
  },
  /** Calendar days from today until `v` (negative when in the past). */
  daysUntil: (v: string | Date | null | undefined): number | null => {
    const d = toDate(v)
    return d ? differenceInCalendarDays(d, new Date()) : null
  },
  /** yyyy-MM-dd in the user's local timezone (for <input type="date"> and API date fields). */
  isoDate: (d: Date = new Date()) => format(d, 'yyyy-MM-dd'),
}

/** Human deadline hint: { text: "Closes in 5 days", tone: 'urgent' | 'normal' | 'past' } or null. */
export function deadlineHint(
  deadline: string | null | undefined,
): { text: string; tone: 'normal' | 'urgent' | 'past' } | null {
  const days = dates.daysUntil(deadline)
  if (days === null) return null
  if (days < 0) return { text: 'Deadline passed', tone: 'past' }
  if (days === 0) return { text: 'Closes today', tone: 'urgent' }
  if (days === 1) return { text: 'Closes tomorrow', tone: 'urgent' }
  if (days <= 7) return { text: `Closes in ${days} days`, tone: 'urgent' }
  return { text: `Apply by ${dates.date(deadline)}`, tone: 'normal' }
}
