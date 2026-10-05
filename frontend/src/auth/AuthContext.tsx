// Authentication state, held above the router so a page reload restores the
// session instead of dropping the user back on the landing page.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useLocation, type Path } from 'react-router-dom'

import { api, onSessionEnded, onTokenChangedElsewhere, tokenStore, type User } from '../api/client'

type AuthState = {
  user: User | null
  /** True until the stored token has been checked, so guards do not redirect early. */
  loading: boolean
  /**
   * The user was signed out by the server refusing the session, or by another
   * tab — not by pressing Log out. Cleared by the next sign-in or sign-out.
   */
  sessionEnded: boolean
  login: (email: string, password: string) => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [sessionEnded, setSessionEnded] = useState(false)

  // Whichever request finds out first — the check on load below, or any call
  // from any screen. client.ts has dropped the token and announces each
  // refused token once, however many requests it was refused on.
  // Subscribed before that first check runs, so its answer is heard.
  useEffect(() => onSessionEnded(() => {
    setUser(null)
    setSessionEnded(true)
  }), [])

  const refresh = useCallback(async () => {
    const token = tokenStore.get()
    if (!token) {
      setUser(null)
      return
    }
    try {
      const current = await api.me()
      // Another tab may have signed in as someone else while this was asked.
      if (tokenStore.get() !== token) return
      setUser(current)
      setSessionEnded(false)
    } catch {
      // A refused token has already ended the session, above. Anything else
      // — the API restarting, a network blip — is no reason to sign out.
    }
  }, [])

  // Validate any stored token once on mount. The token is checked against the
  // server rather than trusted, so an account deactivated since it was issued
  // does not keep working.
  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  // Tabs share the token but not this state. A sign-in or a password change
  // in another tab leaves a token here to pick up; a sign-out there takes it
  // away.
  const signedIn = user !== null
  useEffect(() => onTokenChangedElsewhere(token => {
    if (token) {
      void refresh()
    } else if (signedIn) {
      setUser(null)
      setSessionEnded(true)
    }
  }), [refresh, signedIn])

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password)
    tokenStore.set(result.access_token)
    setUser(result.user)
    setSessionEnded(false)
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    setSessionEnded(false)
  }, [])

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    const result = await api.changePassword(currentPassword, newPassword)
    // The change revoked every earlier token, the one this tab was using
    // included; carrying on means carrying on with the new one.
    tokenStore.set(result.access_token)
    setUser(result.user)
  }, [])

  const value = useMemo(
    () => ({ user, loading, sessionEnded, login, changePassword, logout, refresh }),
    [user, loading, sessionEnded, login, changePassword, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside an AuthProvider')
  return context
}

/** What RequireAuth hands the sign-in page when it turns a signed-out user away. */
export type SignInRedirect = {
  /** The page they were on, or asked for. */
  from?: Partial<Path>
  /** Their session ended under them, rather than them never having had one. */
  sessionEnded?: boolean
}

export const SESSION_ENDED_NOTICE = 'Your session has ended. Please sign in again.'

/**
 * For a page that signs people in: where to send them once they have, and
 * what to tell them first. They go back to the page RequireAuth turned them
 * away from, so a lapsed session costs them only the sign-in.
 */
export function useSignInRedirect(): { destination: string; notice: string | null } {
  const state = useLocation().state as SignInRedirect | null
  const from = state?.from
  // Only ever back into the app. History state outlives the visit that set it.
  const destination = from?.pathname === '/app' || from?.pathname?.startsWith('/app/')
    ? `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`
    : '/app'
  return { destination, notice: state?.sessionEnded ? SESSION_ENDED_NOTICE : null }
}
