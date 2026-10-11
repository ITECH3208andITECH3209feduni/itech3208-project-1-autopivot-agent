// The one scroll lock every dialog shares. Dialogs nest — a confirmation's
// Modal inside a component that also locks, a preview inside LibraryModal —
// and React releases them in whatever order its commit happens to run, so the
// lock has to come out right for any order at all.

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { lockPageScroll } from './pageScrollLock'

const { body } = document

describe('lockPageScroll', () => {
  let held: Array<() => void> = []

  function lock() {
    const release = lockPageScroll()
    held.push(release)
    return release
  }

  beforeEach(() => {
    // Deliberately not what the lock writes and not empty either, so that
    // "put back" cannot be mistaken for "cleared" or "left alone".
    body.style.overflow = 'scroll'
    body.style.paddingRight = '3px'
  })

  afterEach(() => {
    // A failed assertion must not strand a hold that the next test inherits.
    held.forEach(release => release())
    held = []
    body.removeAttribute('style')
  })

  it('keeps the page still until the last dialog lets go, then puts the page back', () => {
    const outer = lock()
    const inner = lock()
    expect(body.style.overflow).toBe('hidden')

    inner()
    expect(body.style.overflow).toBe('hidden')

    outer()
    expect(body.style.overflow).toBe('scroll')
    expect(body.style.paddingRight).toBe('3px')
  })

  it('puts the page back when the first dialog to lock is the first to let go', () => {
    // How the removal confirmation closes: its Modal locked first and its
    // parent's hook second, and React tears the Modal down first.
    const first = lock()
    const second = lock()

    first()
    expect(body.style.overflow).toBe('hidden')

    second()
    expect(body.style.overflow).toBe('scroll')
    expect(body.style.paddingRight).toBe('3px')
  })

  it('does not let a dialog that lets go twice free the page from under another', () => {
    const first = lock()
    const second = lock()

    first()
    first()
    expect(body.style.overflow).toBe('hidden')

    second()
    expect(body.style.overflow).toBe('scroll')
  })

  it('reads the page afresh each time it goes from unlocked to locked', () => {
    lock()()
    body.style.overflow = 'auto'

    lock()()

    expect(body.style.overflow).toBe('auto')
  })

  it('pads the page by the width of the scrollbar it hides', () => {
    // jsdom does no layout, so the two widths are stated: a 1024px window
    // whose document is 1009px wide has a 15px scrollbar.
    const innerWidth = Object.getOwnPropertyDescriptor(window, 'innerWidth')
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })
    Object.defineProperty(document.documentElement, 'clientWidth', { configurable: true, value: 1009 })
    try {
      const release = lock()
      expect(body.style.paddingRight).toBe('15px')

      release()
      expect(body.style.paddingRight).toBe('3px')
    } finally {
      Reflect.deleteProperty(document.documentElement, 'clientWidth')
      if (innerWidth) Object.defineProperty(window, 'innerWidth', innerWidth)
      else Reflect.deleteProperty(window, 'innerWidth')
    }
  })
})
