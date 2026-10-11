// Runs before every test file. Each piece is here because a test would
// otherwise fail — or pass — for a reason that has nothing to do with the app.

import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// jsdom does no layout, so it has no media queries to answer and leaves
// matchMedia out entirely; every screen that picks a layout with
// useMediaQuery would throw. Every query reports false, which is the desktop
// layout.
Object.defineProperty(window, 'matchMedia', {
  configurable: true,
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }),
})

// Nor does it mint object URLs, which the upload form uses to preview a file
// before it is sent. Each call gets a URL of its own because the previews are
// keyed on it.
let objectUrls = 0
URL.createObjectURL = () => `blob:test/${++objectUrls}`
URL.revokeObjectURL = () => {}

// No test may reach a server. Each one spies on the API client methods it
// needs; a request that gets past those lands here and is refused, rather than
// going out over the network. A plain function rather than vi.fn(), so the
// restoreAllMocks below can never reset it into one that answers.
vi.stubGlobal('fetch', () => Promise.reject(new Error('A test tried to make a real request.')))

afterEach(() => {
  // Testing Library only unmounts by itself when test globals are switched on,
  // and they are not. Without this a dialog left open by one test would still
  // be mounted — still holding the page's scroll lock — in the next.
  cleanup()
  // After the unmount, so the effects that clean up on unmount still see the
  // spies they were rendered against.
  vi.restoreAllMocks()
})
