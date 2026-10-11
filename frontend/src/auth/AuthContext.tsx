
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
  loading: boolean
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
      if (tokenStore.get() !== token) return
      setUser(current)
      setSessionEnded(false)
    } catch {
    }
  }, [])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

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

export type SignInRedirect = {
  from?: Partial<Path>
  sessionEnded?: boolean
}

export const SESSION_ENDED_NOTICE = 'Your session has ended. Please sign in again.'

export function useSignInRedirect(): { destination: string; notice: string | null } {
  const state = useLocation().state as SignInRedirect | null
  const from = state?.from
  const destination = from?.pathname === '/app' || from?.pathname?.startsWith('/app/')
    ? `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`
    : '/app'
  return { destination, notice: state?.sessionEnded ? SESSION_ENDED_NOTICE : null }
}
