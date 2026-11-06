import { afterEach, vi } from 'vitest'

// Monaco probes clipboard commands during import; jsdom does not implement
// this browser API, so report those commands as unsupported in unit tests.
if (typeof document.queryCommandSupported !== 'function') {
  Object.defineProperty(document, 'queryCommandSupported', {
    writable: true,
    configurable: true,
    value: () => false,
  })
}

class ResizeObserverMock {
  observe() {}

  unobserve() {}

  disconnect() {}
}

Object.defineProperty(globalThis, 'ResizeObserver', {
  writable: true,
  configurable: true,
  value: ResizeObserverMock,
})

Object.defineProperty(globalThis, 'matchMedia', {
  writable: true,
  configurable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

Object.defineProperty(window, 'scrollTo', {
  writable: true,
  configurable: true,
  value: vi.fn(),
})

afterEach(() => {
  vi.clearAllMocks()
})
