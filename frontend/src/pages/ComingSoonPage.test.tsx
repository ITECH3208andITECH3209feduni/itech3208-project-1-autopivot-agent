// The public coming-soon page shows real photographs of an actual vehicle
// between the hero and the footer. signInReturn.test.tsx already covers the
// login hand-over on this page; this file is scoped to the new showcase
// section only, so it does not repeat that.

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import ComingSoonPage from './ComingSoonPage'

describe('ComingSoonPage', () => {
  it('shows the real-photo showcase, defaulting to the Front angle', () => {
    render(
      <MemoryRouter>
        <ComingSoonPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: 'A real car, not a mockup.' })).toBeTruthy()
    expect(screen.getByRole('img', { name: /front/i }).getAttribute('src')).toBe('/demo-car/front.jpg')
    expect(screen.getByRole('group', { name: /angle/i })).toBeTruthy()
  })
})
