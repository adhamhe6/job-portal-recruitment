import { afterEach, describe, expect, it, vi } from 'vitest'
import { dates, deadlineHint, fmt, formatExperienceRange, formatSalaryRange } from './format'
import { initials, pluralize, safeRedirect } from './utils'

afterEach(() => vi.useRealTimers())

describe('money', () => {
  it('formats with the currency of the job (never a hard-coded symbol)', () => {
    expect(fmt.money(90000, 'EUR')).toBe('€90,000')
    expect(fmt.money('90000.00', 'USD')).toBe('$90,000')
    expect(fmt.money(1234.5, 'GBP', false)).toBe('£1,235')
    expect(fmt.money(null)).toBe('—')
    expect(fmt.money('abc')).toBe('—')
  })
  it('formats salary ranges (decimal strings from the API)', () => {
    expect(formatSalaryRange('80000.00', '105000.00', 'EUR')).toBe('€80K – €105K')
    expect(formatSalaryRange('80000', '80000', 'USD')).toBe('$80K')
    expect(formatSalaryRange('50000', null, 'GBP')).toBe('From £50K')
    expect(formatSalaryRange(null, '90000', 'CAD')).toBe('Up to CA$90K')
    expect(formatSalaryRange(null, null)).toBeNull()
    expect(formatSalaryRange('90000', '120000', 'EUR', false)).toBe('€90,000 – €120,000')
  })
  it('survives an unknown currency code', () => {
    expect(() => fmt.money(10, 'XYZ1')).not.toThrow()
  })
})

describe('numbers & labels', () => {
  it('formats experience, percentages, labels', () => {
    expect(formatExperienceRange('0.0', null)).toBe('No experience required')
    expect(formatExperienceRange('4.0', null)).toBe('4+ yrs')
    expect(formatExperienceRange('2.0', '5.0')).toBe('2–5 yrs')
    expect(fmt.percent(0.824)).toBe('82%')
    expect(fmt.int('1234567')).toBe('1,234,567')
    expect(fmt.label('FULL_TIME')).toBe('Full time')
  })
})

describe('dates', () => {
  it('formats API dates and timestamps', () => {
    expect(dates.date('2026-11-06')).toBe('Nov 6, 2026')
    expect(dates.date(null)).toBe('—')
    expect(dates.date('not a date')).toBe('—')
  })
  it('relative time', () => {
    vi.useFakeTimers({ now: new Date('2026-10-07T12:00:00Z') })
    expect(dates.relative('2026-10-07T11:59:50Z')).toBe('just now')
    expect(dates.relative('2026-10-04T12:00:00Z')).toBe('3 days ago')
  })
  it('deadline hints: urgency tiers', () => {
    vi.useFakeTimers({ now: new Date('2026-10-07T12:00:00') })
    expect(deadlineHint(null)).toBeNull()
    expect(deadlineHint('2026-10-06')).toEqual({ text: 'Deadline passed', tone: 'past' })
    expect(deadlineHint('2026-10-07')).toEqual({ text: 'Closes today', tone: 'urgent' })
    expect(deadlineHint('2026-10-08')).toEqual({ text: 'Closes tomorrow', tone: 'urgent' })
    expect(deadlineHint('2026-10-12')).toEqual({ text: 'Closes in 5 days', tone: 'urgent' })
    expect(deadlineHint('2026-11-06')).toEqual({ text: 'Apply by Nov 6, 2026', tone: 'normal' })
  })
})

describe('utils', () => {
  it('initials', () => {
    expect(initials('Northwind Labs')).toBe('NL')
    expect(initials('Orbit')).toBe('OR')
    expect(initials('  ')).toBe('?')
    expect(initials(null)).toBe('?')
  })
  it('safeRedirect only allows same-origin paths', () => {
    expect(safeRedirect('/jobs/1?x=1')).toBe('/jobs/1?x=1')
    expect(safeRedirect('//evil.com')).toBe('/dashboard')
    expect(safeRedirect('https://evil.com')).toBe('/dashboard')
    expect(safeRedirect('/\\evil.com')).toBe('/dashboard')
    expect(safeRedirect(null, '/x')).toBe('/x')
  })
  it('pluralize', () => {
    expect(pluralize(1, 'job')).toBe('1 job')
    expect(pluralize(2, 'job')).toBe('2 jobs')
    expect(pluralize(0, 'application')).toBe('0 applications')
  })
})
