// What the API client does when the server stops accepting its token.
//
// Every call goes through request() or fetchFile(), so a 401 is noticed there
// rather than in each screen. The token is dropped only if it is still the one
// that was refused: a screen fires several requests at once and each comes
// back refused, and a straggler can arrive after the user has already signed
// in again, here or in another tab.

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, onSessionEnded, onTokenChangedElsewhere, tokenStore } from './client'

const TOKEN_KEY = 'autopivot.token'

function reply(status: number, body: unknown = null): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const refused = () => reply(401, { detail: 'Not authenticated.' })

/** The bearer token a fetch call carried, if any. */
function sentToken(call: Parameters<typeof fetch>): string | null {
  const header = new Headers(call[1]?.headers).get('Authorization')
  return header?.startsWith('Bearer ') ? header.slice('Bearer '.length) : null
}

beforeEach(() => {
  localStorage.clear()
})

describe('A request the server refuses with a 401', () => {
  it('drops the token that was refused', async () => {
    tokenStore.set('expired')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(refused())

    await expect(api.navCounts()).rejects.toMatchObject({ status: 401 })

    expect(tokenStore.get()).toBeNull()
  })

  it('ends the session once, however many requests were refused together', async () => {
    tokenStore.set('revoked')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => refused())
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem')
    const ended = vi.fn()
    const stop = onSessionEnded(ended)

    const results = await Promise.allSettled([
      api.navCounts(), api.dashboardStats(), api.listings(), api.backdrops(),
    ])
    stop()

    expect(results.map(result => result.status)).toEqual(['rejected', 'rejected', 'rejected', 'rejected'])
    expect(ended).toHaveBeenCalledTimes(1)
    expect(removeItem.mock.calls.filter(([key]) => key === TOKEN_KEY)).toHaveLength(1)
  })

  it('leaves alone a token stored while the refused request was in flight', async () => {
    tokenStore.set('old')
    let answer!: (response: Response) => void
    vi.spyOn(globalThis, 'fetch').mockReturnValue(new Promise(resolve => { answer = resolve }))
    const ended = vi.fn()
    const stop = onSessionEnded(ended)

    const straggler = api.navCounts()
    // Signed in again, here or in another tab, before the old answer came back.
    tokenStore.set('fresh')
    answer(refused())
    await expect(straggler).rejects.toMatchObject({ status: 401 })
    stop()

    expect(tokenStore.get()).toBe('fresh')
    expect(ended).not.toHaveBeenCalled()
  })

  it('ends the session when it was an image that was refused', async () => {
    tokenStore.set('expired')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply(401))
    const ended = vi.fn()
    const stop = onSessionEnded(ended)

    await expect(api.fetchFile('/api/files/listings/12/front.jpg')).rejects.toBeInstanceOf(ApiError)
    stop()

    expect(tokenStore.get()).toBeNull()
    expect(ended).toHaveBeenCalledTimes(1)
  })

  it('is not the end of a session when the request carried no token', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(refused())
    const ended = vi.fn()
    const stop = onSessionEnded(ended)

    await expect(api.me()).rejects.toMatchObject({ status: 401 })
    stop()

    expect(ended).not.toHaveBeenCalled()
  })
})

describe('Signing in', () => {
  it('never sends the stored token, so a mistyped password cannot end the session', async () => {
    tokenStore.set('still-good')
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValue(reply(401, { detail: 'Incorrect email or password.' }))
    const ended = vi.fn()
    const stop = onSessionEnded(ended)

    await expect(api.login('pat@first.example.com', 'not-my-password'))
      .rejects.toMatchObject({ status: 401, message: 'Incorrect email or password.' })
    stop()

    expect(sentToken(fetch.mock.calls[0])).toBeNull()
    expect(tokenStore.get()).toBe('still-good')
    expect(ended).not.toHaveBeenCalled()
  })
})

describe('Changing the password', () => {
  it('answers with the new session, as signing in does', async () => {
    tokenStore.set('before-the-change')
    const session = {
      access_token: 'after-the-change', token_type: 'bearer', expires_in: 28800,
      user: {
        id: 7, email: 'pat@first.example.com', first_name: 'Pat', last_name: 'Nguyen',
        role: 'dealership_staff', is_active: true, must_change_password: false, dealership: null,
      },
    }
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply(200, session))

    await expect(api.changePassword('Initial-password-1', 'A-new-private-password-123'))
      .resolves.toEqual(session)
    expect(sentToken(fetch.mock.calls[0])).toBe('before-the-change')
  })
})

describe('Another tab', () => {
  it('storing, replacing or removing the token is reported with the token now stored', () => {
    const seen: (string | null)[] = []
    const stop = onTokenChangedElsewhere(token => seen.push(token))
    // What the other tab's writes look like from here: the shared storage has
    // already changed by the time the event arrives.
    const elsewhere = (key: string | null, write: () => void) => {
      write()
      window.dispatchEvent(new StorageEvent('storage', { key, storageArea: localStorage }))
    }

    elsewhere(TOKEN_KEY, () => localStorage.setItem(TOKEN_KEY, 'signed-in-there'))
    elsewhere(TOKEN_KEY, () => localStorage.setItem(TOKEN_KEY, 'password-changed-there'))
    elsewhere(TOKEN_KEY, () => localStorage.removeItem(TOKEN_KEY))
    elsewhere('some.other.key', () => localStorage.setItem('some.other.key', 'x'))
    // localStorage.clear() in another tab arrives with no key at all.
    elsewhere(null, () => localStorage.clear())
    stop()
    elsewhere(TOKEN_KEY, () => localStorage.setItem(TOKEN_KEY, 'after-unsubscribing'))

    expect(seen).toEqual(['signed-in-there', 'password-changed-there', null, null])
  })
})
