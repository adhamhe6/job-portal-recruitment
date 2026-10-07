import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { useUrlState } from '../useUrlState'

const DEFAULTS = { q: '', sort: 'newest', page: 1, skill: [] as string[] }

function setup(url = '/') {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>
  )
  return renderHook(
    () => {
      const [state, update, reset] = useUrlState(DEFAULTS)
      return { state, update, reset, search: useLocation().search }
    },
    { wrapper },
  )
}

describe('useUrlState', () => {
  it('reads scalars (typed by their default) and repeated params', () => {
    const { result } = setup('/?q=dev&page=3&skill=a&skill=b&sort=title')
    expect(result.current.state).toEqual({ q: 'dev', page: 3, skill: ['a', 'b'], sort: 'title' })
  })

  it('falls back to defaults for missing or invalid values', () => {
    const { result } = setup('/?page=abc')
    expect(result.current.state).toEqual(DEFAULTS)
  })

  it('writes only non-default values and resets the page when filters change', () => {
    const { result } = setup('/?page=4')
    act(() => result.current.update({ q: 'react' }))
    expect(result.current.search).toBe('?q=react')
    act(() => result.current.update({ page: 2 }, { resetPage: false }))
    expect(new URLSearchParams(result.current.search).get('page')).toBe('2')
    act(() => result.current.update({ q: '' }))
    expect(result.current.search).toBe('')
  })

  it('serialises arrays as repeated params', () => {
    const { result } = setup()
    act(() => result.current.update({ skill: ['Python', 'SQL'] }))
    expect(result.current.search).toBe('?skill=Python&skill=SQL')
    act(() => result.current.update({ skill: [] }))
    expect(result.current.search).toBe('')
  })

  it('composes several updates made in the same tick', () => {
    const { result } = setup()
    act(() => {
      result.current.update({ q: 'x' })
      result.current.update({ sort: 'title' })
    })
    expect(result.current.state).toMatchObject({ q: 'x', sort: 'title' })
  })

  it('reset clears everything or selected keys', () => {
    const { result } = setup('/?q=a&sort=title&skill=x')
    act(() => result.current.reset(['q']))
    expect(new URLSearchParams(result.current.search).has('q')).toBe(false)
    expect(new URLSearchParams(result.current.search).get('sort')).toBe('title')
    act(() => result.current.reset())
    expect(result.current.search).toBe('')
  })
})
