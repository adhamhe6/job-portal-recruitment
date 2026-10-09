import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { tokenStore } from '@/lib/api'
import { server } from './server'

// Lazy route chunks are transformed on first import, which can take a few seconds on a cold cache.
configure({ asyncUtilTimeout: 15000 })

// jsdom gaps that Radix UI / cmdk / charts rely on.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
Element.prototype.scrollIntoView ??= function () {}
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.setPointerCapture ??= () => {}
Element.prototype.releasePointerCapture ??= () => {}
window.scrollTo = (() => {}) as typeof window.scrollTo

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  tokenStore.set(null)
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})
afterAll(() => server.close())
