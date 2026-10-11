// The backdrop library's dialogs, and the page they leave behind.
//
// Every dialog here locks the page's scroll while it is open. The app shell has
// no scroll container of its own — the body scrolls — so a lock that is not
// given back leaves every screen in the app frozen until a reload. These tests
// open and close each removal path and check the body afterwards.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type Backdrop } from '../api/client'
import BackdropsView from './BackdropsView'

const forecourt: Backdrop = {
  id: 1,
  name: 'Forecourt',
  suits_angles: [],
  is_default: true,
  image_url: '/api/files/backdrops/forecourt.jpg',
  created_at: '2026-09-01T09:00:00Z',
}

const studio: Backdrop = {
  id: 2,
  name: 'Studio sweep',
  suits_angles: ['front_three_quarter'],
  is_default: false,
  image_url: '/api/files/backdrops/studio.jpg',
  created_at: '2026-09-02T09:00:00Z',
}

// What the app itself leaves on the body: nothing. Stated rather than read
// back from the body, so a lock leaked by an earlier test cannot become the
// value this one expects.
const PAGE_OVERFLOW = ''

describe('BackdropsView removal dialogs', () => {
  beforeEach(() => {
    document.body.style.overflow = PAGE_OVERFLOW
    vi.spyOn(api, 'backdrops').mockResolvedValue([forecourt, studio])
    // Thumbnails never arrive: they are beside the point, and a fetch that
    // settles after the test has finished would update an unmounted image.
    vi.spyOn(api, 'fetchFile').mockReturnValue(new Promise(() => {}))
  })

  it('gives the page its scrolling back when a removal is cancelled', async () => {
    const user = userEvent.setup()
    render(<BackdropsView />)

    await user.click(await screen.findByRole('button', { name: 'Remove Forecourt' }))
    // Checked while open too, or a dialog that never locked anything would
    // pass the assertion that matters.
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(document.body.style.overflow).toBe('hidden')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.body.style.overflow).toBe(PAGE_OVERFLOW)
  })

  it('gives the page its scrolling back once a removal goes through', async () => {
    vi.spyOn(api, 'backdrops')
      .mockResolvedValueOnce([forecourt, studio])
      .mockResolvedValue([studio])
    vi.spyOn(api, 'deleteBackdrop').mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<BackdropsView />)

    await user.click(await screen.findByRole('button', { name: 'Remove Forecourt' }))
    await user.click(screen.getByRole('button', { name: 'Remove backdrop' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(api.deleteBackdrop).toHaveBeenCalledWith(forecourt.id)
    expect(document.body.style.overflow).toBe(PAGE_OVERFLOW)
  })

  it('gives the page its scrolling back when a removal started from the preview is cancelled', async () => {
    const user = userEvent.setup()
    render(<BackdropsView />)

    await user.click(await screen.findByRole('button', { name: 'Preview Forecourt full size' }))
    await user.click(screen.getByRole('button', { name: 'Remove this backdrop' }))
    // The confirmation replaces the preview rather than stacking on it.
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    expect(document.body.style.overflow).toBe('hidden')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.body.style.overflow).toBe(PAGE_OVERFLOW)
  })
})
