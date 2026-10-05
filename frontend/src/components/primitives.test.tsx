// Modal on its own, as the login and demo dialogs use it — no useDialogKeys
// alongside to take the scroll lock on its behalf.

import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Modal } from './primitives'

describe('Modal', () => {
  it('holds the page still for as long as it is open, then lets go', () => {
    document.body.style.overflow = ''
    const { rerender, unmount } = render(<Modal onClose={() => {}}>Log in</Modal>)
    expect(document.body.style.overflow).toBe('hidden')

    // Every caller passes onClose inline, so each re-render hands over a new
    // function. The page must stay locked through that, not flicker free.
    rerender(<Modal onClose={() => {}}>Log in</Modal>)
    expect(document.body.style.overflow).toBe('hidden')

    unmount()
    expect(document.body.style.overflow).toBe('')
  })
})
