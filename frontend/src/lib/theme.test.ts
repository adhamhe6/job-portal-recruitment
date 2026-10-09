import { describe, expect, it } from 'vitest'
import { setThemePreference } from './theme'

describe('theme', () => {
  it('applies and persists explicit choices, and system falls back to the OS setting', () => {
    setThemePreference('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('talentlens.theme')).toBe('dark')
    setThemePreference('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    setThemePreference('system') // jsdom has no matchMedia -> light
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('talentlens.theme')).toBe('system')
  })
})
