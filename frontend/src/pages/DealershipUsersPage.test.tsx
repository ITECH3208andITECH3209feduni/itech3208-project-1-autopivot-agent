// The team page never offers an administrator the reset on their own row.
//
// A reset signs its target out and swaps their password for a one-time one,
// shown once. Pressed on your own row it ended the session you were using —
// and if the password was not copied in time, locked you out of the account.
// Your own password is changed through Change password instead.

import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type DealershipUser, type User } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import DealershipUsersPage from './DealershipUsersPage'

/** The signed-in administrator, as the team list shows them. */
const ownRow: DealershipUser = {
  id: 1, email: 'admin@first.example.com', first_name: 'Alex', last_name: 'Admin',
  role: 'dealership_admin', is_active: true, must_change_password: false,
}
/** And as GET /auth/me answers for them. */
const administrator: User = {
  ...ownRow,
  dealership: {
    id: 1, name: 'First Motors', location: 'Ballarat', contact_name: null,
    contact_email: null, contact_phone: null, status: 'active', user_count: 3,
  },
}
const colleague: DealershipUser = {
  id: 2, email: 'kim@first.example.com', first_name: 'Kim', last_name: 'Admin',
  role: 'dealership_admin', is_active: true, must_change_password: false,
}
const staff: DealershipUser = {
  id: 3, email: 'sam@first.example.com', first_name: 'Sam', last_name: 'Staff',
  role: 'dealership_staff', is_active: true, must_change_password: false,
}

function renderTeam() {
  return render(
    <MemoryRouter initialEntries={['/app/users']}>
      <AuthProvider>
        <DealershipUsersPage />
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** The row for the account with this email. */
async function row(email: string): Promise<HTMLElement> {
  const cell = await screen.findByText(new RegExp(email.replace(/\./g, '\\.')))
  const article = cell.closest('article')
  if (!article) throw new Error(`No row holds ${email}.`)
  return article
}

describe('DealershipUsersPage', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('autopivot.token', 'administrator-token')
    vi.spyOn(api, 'me').mockResolvedValue(administrator)
    vi.spyOn(api, 'dealershipUsers').mockResolvedValue([ownRow, colleague, staff])
  })

  it('offers no reset, and no deactivation, on the administrator’s own row', async () => {
    renderTeam()
    // Wait for the signed-in administrator, not just the list: until then the
    // page cannot know which row is theirs.
    await screen.findByText(/Manage users at First Motors/)

    const own = await row(administrator.email)
    expect(within(own).queryByRole('button', { name: 'Reset password' })).toBeNull()
    expect(within(own).queryByRole('button', { name: 'Deactivate' })).toBeNull()
  })

  it('points the administrator at Change password on their own row instead', async () => {
    renderTeam()
    await screen.findByText(/Manage users at First Motors/)

    const own = await row(administrator.email)
    const change = within(own).getByRole('link', { name: 'Change password' })
    expect(change.getAttribute('href')).toBe('/app/change-password')
  })

  it('still offers reset and deactivation on everyone else’s row', async () => {
    renderTeam()
    await screen.findByText(/Manage users at First Motors/)

    for (const other of [colleague, staff]) {
      const theirs = await row(other.email)
      expect(within(theirs).getByRole('button', { name: 'Reset password' })).toBeTruthy()
      expect(within(theirs).getByRole('button', { name: 'Deactivate' })).toBeTruthy()
      expect(within(theirs).queryByRole('link', { name: 'Change password' })).toBeNull()
    }
  })
})
