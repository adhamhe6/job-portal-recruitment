/**
 * Timezone helpers for interviews. An interview is communicated in an explicit IANA timezone (`Europe/Berlin`); the API
 * stores UTC instants. Everything that shows or edits a time goes through here so the zone is never implicit.
 */

const FALLBACK_ZONES = [
  'UTC',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Paris',
  'Europe/Madrid',
  'Europe/Istanbul',
  'Africa/Cairo',
  'Asia/Riyadh',
  'Asia/Dubai',
  'Asia/Kolkata',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Australia/Sydney',
  'America/Sao_Paulo',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
]

export function isValidTimeZone(tz: string | null | undefined): tz is string {
  if (!tz) return false
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz })
    return true
  } catch {
    return false
  }
}

export function viewerTimeZone(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    return isValidTimeZone(tz) ? tz : 'UTC'
  } catch {
    return 'UTC'
  }
}

/** All IANA zones the browser knows, with `UTC` first and `extra` (e.g. an existing interview's zone) always included. */
export function listTimeZones(extra: readonly string[] = []): string[] {
  let zones: string[] = []
  try {
    const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf
    zones = supported ? supported('timeZone') : []
  } catch {
    zones = []
  }
  if (zones.length === 0) zones = FALLBACK_ZONES
  const set = new Set<string>(['UTC', ...zones, ...extra.filter(isValidTimeZone)])
  return ['UTC', ...[...set].filter((z) => z !== 'UTC').sort()]
}

const safeZone = (tz: string) => (isValidTimeZone(tz) ? tz : 'UTC')

function parts(date: Date, tz: string, opts: Intl.DateTimeFormatOptions) {
  const out: Record<string, string> = {}
  for (const p of new Intl.DateTimeFormat('en-US', { timeZone: safeZone(tz), ...opts }).formatToParts(date)) {
    out[p.type] = p.value
  }
  return out
}

/** Offset of `tz` from UTC at the instant `date`, in minutes (Berlin in summer = +120). */
export function zoneOffsetMinutes(date: Date, tz: string): number {
  const p = parts(date, tz, {
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  const asUtc = Date.UTC(+p.year!, +p.month! - 1, +p.day!, +p.hour!, +p.minute!, +p.second!)
  return Math.round((asUtc - (date.getTime() - date.getMilliseconds())) / 60_000)
}

/** "UTC+02:00" / "UTC−05:30" / "UTC". */
export function offsetLabel(date: Date, tz: string): string {
  const m = zoneOffsetMinutes(date, tz)
  if (m === 0) return 'UTC'
  const sign = m < 0 ? '−' : '+'
  const abs = Math.abs(m)
  return `UTC${sign}${String(Math.floor(abs / 60)).padStart(2, '0')}:${String(abs % 60).padStart(2, '0')}`
}

/** Short zone name at an instant: "CEST", "GMT+2", "UTC". */
export function zoneAbbreviation(date: Date, tz: string): string {
  return parts(date, tz, { timeZoneName: 'short' }).timeZoneName ?? safeZone(tz)
}

/**
 * Read a wall-clock `YYYY-MM-DDTHH:mm` (what `<input type="datetime-local">` yields) in `tz` and return the instant.
 * Returns null for unparsable input. Non-existent local times (DST gap) resolve forward.
 */
export function wallTimeToInstant(local: string, tz: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(local)
  if (!m) return null
  const wall = Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]!)
  if (Number.isNaN(wall)) return null
  let instant = wall - zoneOffsetMinutes(new Date(wall), tz) * 60_000
  // The offset may differ at the real instant (around DST changes): settle once more.
  instant = wall - zoneOffsetMinutes(new Date(instant), tz) * 60_000
  return new Date(instant)
}

/** Add minutes to a wall-clock `YYYY-MM-DDTHH:mm` string (pure calendar arithmetic, no zone involved). */
export function addMinutesToLocal(local: string, minutes: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(local)
  if (!m) return ''
  const d = new Date(Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]!) + minutes * 60_000)
  return d.toISOString().slice(0, 16)
}

/** Minutes between two wall-clock strings (same zone assumed). */
export function minutesBetweenLocal(a: string, b: string): number | null {
  const pa = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(a)
  const pb = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(b)
  if (!pa || !pb) return null
  const t = (m: RegExpExecArray) => Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]!)
  return Math.round((t(pb) - t(pa)) / 60_000)
}

/** `yyyy-MM-ddTHH:mm` from an ISO string carrying its own offset ("2030-05-20T09:00:00+02:00"). */
export const localInputValue = (isoWithOffset: string) => isoWithOffset.slice(0, 16)

/** "yyyy-MM-ddTHH:mm" wall time of an instant as seen in `tz`. */
export function instantToLocalInput(iso: string, tz: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = parts(d, tz, {
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

/** Calendar-day key (`yyyy-MM-dd`) of an instant in `tz`. */
export function dayKey(iso: string, tz: string): string {
  return instantToLocalInput(iso, tz).slice(0, 10)
}

function fmt(date: Date, tz: string, opts: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat('en-US', { timeZone: safeZone(tz), ...opts }).format(date)
}

export const formatDay = (iso: string, tz: string) =>
  fmt(new Date(iso), tz, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })

export const formatClock = (iso: string, tz: string) =>
  fmt(new Date(iso), tz, { hour: 'numeric', minute: '2-digit' })

/**
 * "Thu, Oct 9, 2026 · 2:00 PM – 3:00 PM CEST" in `tz`; the end shows its own date when the interview crosses midnight.
 * The zone abbreviation is always present so the time can never be read as the viewer's local time by accident.
 */
export function formatSlot(startIso: string, endIso: string, tz: string): string {
  const sameDay = dayKey(startIso, tz) === dayKey(endIso, tz)
  const endPart = sameDay ? formatClock(endIso, tz) : `${formatDay(endIso, tz)}, ${formatClock(endIso, tz)}`
  return `${formatDay(startIso, tz)} · ${formatClock(startIso, tz)} – ${endPart} ${zoneAbbreviation(new Date(endIso), tz)}`
}

/** Compact clock range for agenda rows: "2:00 – 3:00 PM CEST". */
export function formatClockRange(startIso: string, endIso: string, tz: string): string {
  return `${formatClock(startIso, tz)} – ${formatClock(endIso, tz)} ${zoneAbbreviation(new Date(startIso), tz)}`
}

/** Do the two zones have the same UTC offset at this instant? (Then a second "your time" line is noise.) */
export function sameOffset(iso: string, a: string, b: string): boolean {
  const d = new Date(iso)
  return zoneOffsetMinutes(d, a) === zoneOffsetMinutes(d, b)
}
