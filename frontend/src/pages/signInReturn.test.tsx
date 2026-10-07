// Signing in from either public page lands where the user was turned away.
//
// RequireAuth sends a signed-out visitor to "/" with the page they asked for
// in the navigation state, but both public pages ignored it and always opened
// the Overview — a deep link, or a session that lapsed on a vehicle page,
// cost the user their place.

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, type InitialEntry } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type User } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { Landed } from '../test/helpers'
import ComingSoonPage from './ComingSoonPage'
import LandingPage from './LandingPage'

const pat: User = {
  id: 7, email: 'pat@first.example.com', first_name: 'Pat', last_name: 'Nguyen',
  role: 'dealership_staff', is_active: true, must_change_password: false, dealership: null,
}

function renderAt(entry: InitialEntry) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<ComingSoonPage />} />
          <Route path="/preview" element={<LandingPage />} />
          <Route path="/app/*" element={<Landed />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function logIn() {
  const user = userEvent.setup()
  await user.click(screen.getAllByRole('button', { name: 'Log in' })[0])
  const dialog = await screen.findByRole('dialog')
  await user.type(within(dialog).getByPlaceholderText('you@dealership.co.nz'), pat.email)
  await user.type(within(dialog).getByPlaceholderText('••••••••'), 'Pat-password-123')
  await user.click(within(dialog).getByRole('button', { name: 'Log in' }))
}

/** Where RequireAuth leaves a visitor it turned away from a vehicle page. */
const turnedAwayFrom = (pathname: string) => ({
  pathname,
  state: { from: { pathname: '/app/vehicles/12', search: '?photo=3', hash: '' } },
})

describe.each([
  ['the coming-soon page', '/'],
  ['the landing page', '/preview'],
])('Signing in from %s', (_, page) => {
  beforeEach(() => {
    localStorage.clear()
    vi.spyOn(api, 'login').mockResolvedValue({
      access_token: 'fresh-token', token_type: 'bearer', expires_in: 28800, user: pat,
    })
  })

  it('returns to the page the visitor was turned away from', async () => {
    renderAt(turnedAwayFrom(page))

    await logIn()

    expect(await screen.findByText('Landed on /app/vehicles/12?photo=3')).toBeTruthy()
  })

  it('opens the Overview when nothing sent the visitor here', async () => {
    renderAt(page)

    await logIn()

    expect(await screen.findByText('Landed on /app')).toBeTruthy()
  })

  it('never leaves the app for somewhere the navigation state names', async () => {
    renderAt({ pathname: page, state: { from: { pathname: '/guidelines', search: '', hash: '' } } })

    await logIn()

    expect(await screen.findByText('Landed on /app')).toBeTruthy()
  })
})
