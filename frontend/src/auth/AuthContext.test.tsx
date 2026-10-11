// The session as the whole app sees it: what happens when the server stops
// accepting it, when another tab signs in or out, and when the password is
// changed.
//
// The app used to notice a dead session only when it was next loaded. After an
// expiry, an administrator's reset or a password change elsewhere, every call
// failed while the screen stayed signed in. These tests run the real App over
// a stand-in API that refuses a revoked token wherever it is used, as the real
// one does.

import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import type { Dealership, User } from '../api/client'

const TOKEN_KEY = 'autopivot.token'
const SESSION_ENDED = 'Your session has ended. Please sign in again.'

function dealership(id: number, name: string): Dealership {
  return {
    id, name, location: 'Ballarat', contact_name: null, contact_email: null,
    contact_phone: null, status: 'active', user_count: 3,
  }
}

const pat: User = {
  id: 7, email: 'pat@first.example.com', first_name: 'Pat', last_name: 'Nguyen',
  role: 'dealership_admin', is_active: true, must_change_password: false,
  dealership: dealership(1, 'First Motors'),
}
const sam: User = {
  id: 8, email: 'sam@second.example.com', first_name: 'Sam', last_name: 'Okafor',
  role: 'dealership_staff', is_active: true, must_change_password: false,
  dealership: dealership(2, 'Second Motors'),
}
const PASSWORD = 'Pat-password-123'

type Seen = { method: string; path: string; token: string | null; status: number }

/** The API as far as these screens use it, with sessions that can be revoked. */
class FakeApi {
  private accounts = new Map<string, { user: User; password: string }>()
  /** Live tokens, and whose they are. */
  private sessions = new Map<string, string>()
  private issued = 0
  readonly seen: Seen[] = []
  /** Whose sessions to revoke as soon as a screen starts asking for its data. */
  private revokeOnFirstApiCall: string | null = null
  /** Paths whose next request is not answered until released. */
  private held = new Map<string, Promise<void>>()

  add(user: User, password = PASSWORD) {
    this.accounts.set(user.email, { user, password })
  }

  signIn(email: string): string {
    const token = `token-${++this.issued}`
    this.sessions.set(token, email)
    return token
  }

  revokeSessionsOf(email: string) {
    for (const [token, owner] of this.sessions) if (owner === email) this.sessions.delete(token)
  }

  /**
   * An administrator's reset landing after the app has loaded the user, just
   * as the screen asks for its data: every one of those requests is refused.
   */
  revokeSessionsOfOnceLoaded(email: string) {
    this.revokeOnFirstApiCall = email
  }

  /** Holds the next request to `path` back; call the result to let it be answered. */
  holdNext(path: string): () => void {
    let release!: () => void
    this.held.set(path, new Promise(resolve => { release = resolve }))
    return () => release()
  }

  /** How many requests carrying this token were refused. */
  refused(token: string): number {
    return this.seen.filter(request => request.token === token && request.status === 401).length
  }

  fetch = async (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input), 'http://localhost')
    const gate = this.held.get(url.pathname)
    if (gate) {
      this.held.delete(url.pathname)
      await gate
    }
    const method = init.method ?? 'GET'
    const header = new Headers(init.headers).get('Authorization')
    const token = header?.startsWith('Bearer ') ? header.slice('Bearer '.length) || null : null
    const respond = (status: number, body: unknown) => {
      this.seen.push({ method, path: url.pathname, token, status })
      return new Response(JSON.stringify(body), {
        status, headers: { 'Content-Type': 'application/json' },
      })
    }

    if (this.revokeOnFirstApiCall && url.pathname.startsWith('/api/')) {
      this.revokeSessionsOf(this.revokeOnFirstApiCall)
      this.revokeOnFirstApiCall = null
    }

    if (method === 'POST' && url.pathname === '/auth/login') {
      const { email, password } = JSON.parse(String(init.body))
      const account = this.accounts.get(email)
      if (!account || account.password !== password) {
        return respond(401, { detail: 'Incorrect email or password.' })
      }
      return respond(200, {
        access_token: this.signIn(email), token_type: 'bearer', expires_in: 28800, user: account.user,
      })
    }

    const owner = token ? this.sessions.get(token) : undefined
    const account = owner ? this.accounts.get(owner) : undefined
    if (!account) return respond(401, { detail: 'Not authenticated.' })

    if (method === 'GET' && url.pathname === '/auth/me') return respond(200, account.user)

    if (method === 'POST' && url.pathname === '/auth/change-password') {
      const { current_password, new_password } = JSON.parse(String(init.body))
      if (current_password !== account.password) {
        return respond(400, { detail: 'Current password is incorrect.' })
      }
      account.password = new_password
      account.user = { ...account.user, must_change_password: false }
      // As the real endpoint does: every earlier token stops working,
      // including the one this request was made with.
      this.revokeSessionsOf(account.user.email)
      return respond(200, {
        access_token: this.signIn(account.user.email), token_type: 'bearer',
        expires_in: 28800, user: account.user,
      })
    }

    if (account.user.must_change_password) {
      return respond(403, { detail: 'You must change your initial password before continuing.' })
    }
    if (method === 'GET' && url.pathname === '/api/dashboard/counts') {
      return respond(200, { vehicles: 0, backdrops: 0, needs_review: 0 })
    }
    if (method === 'GET' && url.pathname === '/api/dashboard/stats') {
      return respond(200, { vehicles_this_month: 0, images_processed: 0, needs_review: 0 })
    }
    if (method === 'GET' && url.pathname === '/api/listings') return respond(200, [])
    return respond(404, { detail: 'Not Found' })
  }
}

let server: FakeApi

beforeEach(() => {
  localStorage.clear()
  server = new FakeApi()
  server.add(pat)
  server.add(sam)
  vi.spyOn(globalThis, 'fetch').mockImplementation(server.fetch)
})

/** Loads the app at `path`, as typing it into the address bar would. */
function open(path: string) {
  window.history.replaceState(null, '', path)
  return render(<App />)
}

/** Stores a live session for `user`, as an earlier sign-in would have. */
function signedInAs(user: User): string {
  const token = server.signIn(user.email)
  localStorage.setItem(TOKEN_KEY, token)
  return token
}

/** What another tab writing the token looks like from this one. */
function anotherTabStores(token: string | null) {
  const oldValue = localStorage.getItem(TOKEN_KEY)
  act(() => {
    if (token === null) localStorage.removeItem(TOKEN_KEY)
    else localStorage.setItem(TOKEN_KEY, token)
    window.dispatchEvent(new StorageEvent('storage', {
      key: TOKEN_KEY, oldValue, newValue: token, storageArea: localStorage,
    }))
  })
}

async function signIn(dialog: HTMLElement, email: string, password: string) {
  const user = userEvent.setup()
  await user.type(within(dialog).getByPlaceholderText('you@dealership.co.nz'), email)
  await user.type(within(dialog).getByPlaceholderText('••••••••'), password)
  await user.click(within(dialog).getByRole('button', { name: 'Log in' }))
}

describe('A session the server stops accepting', () => {
  it('signs the user out once and asks them to sign in again', async () => {
    const token = signedInAs(pat)
    // An administrator resets Pat's password while the overview loads.
    server.revokeSessionsOfOnceLoaded(pat.email)
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem')

    open('/app')

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(SESSION_ENDED)).toBeTruthy()
    expect(window.location.pathname).toBe('/')
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    // The overview asks for several things at once and every one of them was
    // refused — the session still ended, and the token was cleared, once.
    await waitFor(() => expect(server.refused(token)).toBeGreaterThanOrEqual(3))
    expect(removeItem.mock.calls.filter(([key]) => key === TOKEN_KEY)).toHaveLength(1)
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })

  it('puts the user back where they were once they have signed in again', async () => {
    const token = signedInAs(pat)
    server.revokeSessionsOfOnceLoaded(pat.email)
    open('/app/settings')

    await signIn(await screen.findByRole('dialog'), pat.email, PASSWORD)

    expect(await screen.findByText('This view is not built yet.')).toBeTruthy()
    expect(window.location.pathname).toBe('/app/settings')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).not.toBe(token)
    expect(localStorage.getItem(TOKEN_KEY)).not.toBeNull()
  })

  it('found out on loading the app, still explains and still leads back', async () => {
    const token = signedInAs(pat)
    // Expired overnight: refused from the very first request.
    server.revokeSessionsOf(pat.email)
    open('/app/settings')

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(SESSION_ENDED)).toBeTruthy()
    expect(server.refused(token)).toBeGreaterThanOrEqual(1)

    await signIn(dialog, pat.email, PASSWORD)
    expect(await screen.findByText('This view is not built yet.')).toBeTruthy()
    expect(window.location.pathname).toBe('/app/settings')
  })

  it('is not what a deliberate log out looks like', async () => {
    signedInAs(pat)
    open('/app/settings')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Log out' }))

    await waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByText(SESSION_ENDED)).toBeNull()
  })
})

describe('Another tab', () => {
  it('signing out signs this tab out too', async () => {
    signedInAs(pat)
    open('/app/settings')
    await screen.findByRole('button', { name: 'Log out' })

    anotherTabStores(null)

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(SESSION_ENDED)).toBeTruthy()
    expect(window.location.pathname).toBe('/')
  })

  it('signing in is noticed here', async () => {
    open('/no-such-page')
    await screen.findByRole('button', { name: 'Back to the start' })

    anotherTabStores(server.signIn(pat.email))

    expect(await screen.findByRole('button', { name: 'Back to Overview' })).toBeTruthy()
  })

  it('switching to another account switches this tab to it', async () => {
    signedInAs(pat)
    open('/app/settings')
    expect(await screen.findByText('First Motors')).toBeTruthy()

    anotherTabStores(server.signIn(sam.email))

    expect(await screen.findByText('Second Motors')).toBeTruthy()
    expect(screen.queryByText('First Motors')).toBeNull()
  })

  it('switching account while this tab is still loading leaves it on the new account', async () => {
    signedInAs(pat)
    // This tab's check of Pat's session is slow to come back...
    const answerPat = server.holdNext('/auth/me')
    open('/app/settings')

    // ...and before it does, another tab signs in as Sam.
    anotherTabStores(server.signIn(sam.email))
    await waitFor(() => expect(server.seen.some(r => r.path === '/auth/me')).toBe(true))
    await act(async () => { answerPat() })

    expect(await screen.findByText('Second Motors')).toBeTruthy()
    expect(screen.queryByText('First Motors')).toBeNull()
  })

  it('changing the password keeps this tab signed in on the new token', async () => {
    const before = signedInAs(pat)
    open('/app/settings')
    await screen.findByRole('button', { name: 'Log out' })

    // The other tab's change revokes the token this one loaded with.
    server.revokeSessionsOf(pat.email)
    const after = server.signIn(pat.email)
    anotherTabStores(after)
    await userEvent.setup().click(screen.getByRole('link', { name: /Vehicles/ }))

    await waitFor(() => expect(server.seen.some(r => r.token === after && r.status === 200)).toBe(true))
    expect(server.refused(before)).toBe(0)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).toBe(after)
  })
})

describe('Changing the password', () => {
  it('carries on signed in, on the token the change handed back', async () => {
    server.add({ ...pat, must_change_password: true }, 'Initial-password-1')
    const before = signedInAs(pat)
    open('/app/change-password')
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Current password'), 'Initial-password-1')
    await user.type(screen.getByLabelText('New password'), 'A-new-private-password-123')
    await user.type(screen.getByLabelText('Confirm new password'), 'A-new-private-password-123')
    await user.click(screen.getByRole('button', { name: 'Change password' }))

    await waitFor(() => {
      const stored = localStorage.getItem(TOKEN_KEY)
      expect(stored).not.toBe(before)
      expect(stored).not.toBeNull()
    })
    const after = localStorage.getItem(TOKEN_KEY)
    const change = server.seen.findIndex(r => r.path === '/auth/change-password')
    expect(server.seen[change]).toMatchObject({ token: before, status: 200 })
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeTruthy()
    expect(window.location.pathname).toBe('/app')
    expect(screen.queryByRole('dialog')).toBeNull()
    // Everything the overview asked for went out on the new token and was
    // answered; the old one was never used again.
    await waitFor(() => expect(server.seen.length).toBeGreaterThan(change + 2))
    const since = server.seen.slice(change + 1)
    expect(since.every(r => r.token === after && r.status === 200)).toBe(true)
    expect(server.refused(before)).toBe(0)
  })
})
