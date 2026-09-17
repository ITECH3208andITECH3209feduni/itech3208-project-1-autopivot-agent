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

import { ApiError, api, tokenStore, type User } from '../api/client'

type AuthState = {
  user: User | null
  /** True until the stored token has been checked, so guards do not redirect early. */
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) {
      setUser(null)
      return
    }
    try {
      setUser(await api.me())
    } catch (err) {
      // A rejected token is worth discarding; a network blip is not, since
      // clearing here would silently sign the user out when the API restarts.
      if (err instanceof ApiError && err.status === 401) {
        tokenStore.clear()
        setUser(null)
      }
    }
  }, [])

  // Validate any stored token once on mount. The token is checked against the
  // server rather than trusted, so an account deactivated since it was issued
  // does not keep working.
  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password)
    tokenStore.set(result.access_token)
    setUser(result.user)
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, logout, refresh }),
    [user, loading, login, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside an AuthProvider')
  return context
}
