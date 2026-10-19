// Real demo-car photographs on the public coming-soon page: eight angles of
// one actual vehicle, each served as a static /demo-car/*.jpg file so a
// logged-out visitor never hits the authenticated file-serving path (that
// requires a bearer token this page's visitor never has). No angle has a
// processed ("after") image yet. The comparison branch is proven here
// against injected fixture data, so wiring in a real "after" image later
// needs no rework to this component.

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import RealPhotoShowcase, { SHOWCASE_ANGLES, type ShowcaseAngle } from './RealPhotoShowcase'

describe('SHOWCASE_ANGLES', () => {
  it('lists all 8 real angles, in the walking order the capture app uses, with no after image yet', () => {
    expect(SHOWCASE_ANGLES.map(angle => [angle.label, angle.before])).toEqual([
      ['Front', '/demo-car/front.jpg'],
      ['Front-right corner', '/demo-car/frontRightCorner.jpg'],
      ['Right side', '/demo-car/rightSide.jpg'],
      ['Rear-right corner', '/demo-car/rearRightCorner.jpg'],
      ['Rear', '/demo-car/rear.jpg'],
      ['Rear-left corner', '/demo-car/rearLeftCorner.jpg'],
      ['Left side', '/demo-car/leftSide.jpg'],
      ['Front-left corner', '/demo-car/frontLeftCorner.jpg'],
    ])
  })

  it('leaves "after" genuinely absent rather than an empty string or placeholder', () => {
    expect(SHOWCASE_ANGLES.every(angle => angle.after === undefined)).toBe(true)
  })
})

describe('RealPhotoShowcase', () => {
  it('renders the selected angle as a plain static <img>, never through an authenticated path', () => {
    render(<RealPhotoShowcase />)

    // Not AuthedImage: a real <img src="/demo-car/..."> that Vite serves
    // straight from frontend/public with no token and no fetch. If this ever
    // routed through AuthedImage/api.fetchFile instead, there would be no
    // such <img> — api.fetchFile is unmocked here and the test/setup.ts
    // fetch stub rejects every call, so AuthedImage would render its
    // unavailable-placeholder <div>, not an <img> with this literal src.
    const hero = screen.getByRole('img', { name: /front/i })
    expect(hero.getAttribute('src')).toBe('/demo-car/front.jpg')
  })

  it('offers every angle, in order, as a selectable thumbnail', () => {
    render(<RealPhotoShowcase />)

    const group = screen.getByRole('group', { name: /angle/i })
    const buttons = within(group).getAllByRole('button')
    expect(buttons.map(button => button.textContent)).toEqual([
      'Front', 'Front-right corner', 'Right side', 'Rear-right corner',
      'Rear', 'Rear-left corner', 'Left side', 'Front-left corner',
    ])
    expect(buttons[0].getAttribute('aria-pressed')).toBe('true')
  })

  it('swaps the real photo shown when a different angle is picked', async () => {
    const user = userEvent.setup()
    render(<RealPhotoShowcase />)

    await user.click(screen.getByRole('button', { name: 'Rear' }))

    expect(screen.getByRole('img', { name: /rear/i }).getAttribute('src')).toBe('/demo-car/rear.jpg')
    // The old main photo is gone outright, not merely joined by a new one.
    expect(screen.queryByRole('img', { name: /^front /i })).toBeNull()
  })

  it('shows today\'s real photo plainly, with no slider and no "Processed" claim, since no angle has an after image', () => {
    render(<RealPhotoShowcase />)

    expect(screen.queryByRole('slider')).toBeNull()
    expect(screen.queryByText('Processed')).toBeNull()
    expect(screen.getByText(/processed version is coming soon/i)).toBeTruthy()
    // The honest fallback still names what the photo is: the real original.
    expect(screen.getByText('Original')).toBeTruthy()
  })

  it('renders a real before/after comparison with no code changes once an angle gets an after image', async () => {
    const user = userEvent.setup()
    const angles: ShowcaseAngle[] = [
      { id: 'front', label: 'Front', before: '/demo-car/front.jpg', after: '/demo-car/front-after.jpg' },
    ]
    render(<RealPhotoShowcase angles={angles} />)

    expect(screen.getByText('Original')).toBeTruthy()
    expect(screen.getByText('Processed')).toBeTruthy()
    expect(screen.getByRole('img', { name: /after processing/i }).getAttribute('src')).toBe('/demo-car/front-after.jpg')
    // The per-frame "nothing to compare yet" fallback caption is specific to
    // an angle with no after image — it must not survive once one is added.
    // (The section's own intro copy still says "coming soon" in general,
    // which stays true today regardless of this one fixture.)
    expect(screen.queryByText('This is the original, unedited photograph. The processed version is coming soon.')).toBeNull()

    const slider = screen.getByRole('slider', { name: /before and after divider/i }) as HTMLInputElement
    expect(slider.value).toBe('50')

    await user.click(screen.getByRole('button', { name: 'Show original' }))
    expect(slider.value).toBe('100')
  })

  it('never blocks native touch-scroll on a plain photo frame, since no angle has an after image today', () => {
    render(<RealPhotoShowcase />)

    // touch-action: 'none' suppresses the browser's own touch-scroll
    // handling for gestures starting on this element. With no drag-to-
    // compare slider attached (no `after` image exists for any angle yet),
    // applying it anyway would trap a visitor's thumb mid-scroll for no
    // reason -- a real regression, not a style nitpick.
    const frame = screen.getByRole('img', { name: /front/i }).parentElement!
    expect(frame.style.touchAction).not.toBe('none')
  })

  it('blocks native touch-scroll only once a drag-to-compare slider is actually present', () => {
    const angles: ShowcaseAngle[] = [
      { id: 'front', label: 'Front', before: '/demo-car/front.jpg', after: '/demo-car/front-after.jpg' },
    ]
    render(<RealPhotoShowcase angles={angles} />)

    const frame = screen.getByRole('img', { name: /unedited/i }).parentElement!
    expect(frame.style.touchAction).toBe('none')
  })
})
