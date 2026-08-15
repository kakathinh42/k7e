/**
 * auth/AuthContext.tsx — one provider spanning the two auth modes.
 *
 * dev:      instantly authenticated as {id: 'dev'}; logout is a no-op.
 * password: native email+password login (self-issued session). Boot rehydrates
 *           the persisted session; a 401 clears it and RequireAuth routes to
 *           /login, whose form calls submitCredentials.
 *
 * The provider mirrors the current token into the framework-free tokenStore
 * so api.ts can attach it without hooks, and subscribes to the store's 401
 * signal to flip to `unauthenticated`. Claims are decoded client-side for
 * display only — the API re-verifies.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { authMode, identityClaim, type AuthMode } from './config'
import { secondsUntilExpiry } from './jwt'
import * as tokenStore from './tokenStore'
import {
  clearPersistedToken as clearPersistedPasswordToken,
  loadPersistedToken as loadPersistedPasswordToken,
  passwordLogin,
  passwordRegister,
  refreshSession,
} from './password'

//: How long before a session's expiry to fire the silent refresh (seconds).
const REFRESH_LEAD_SECONDS = 60
//: Floor so a near-expired token still schedules a (near-immediate) attempt.
const MIN_REFRESH_DELAY_SECONDS = 5

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface AuthUser {
  id: string
  email?: string
  name?: string
}

export interface AuthState {
  mode: AuthMode
  status: AuthStatus
  user: AuthUser | null
  /** password mode: submit credentials (register when true), adopt on success. */
  submitCredentials: (
    email: string,
    password: string,
    register: boolean,
  ) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function userFromClaims(claims: Record<string, unknown>): AuthUser {
  const idClaim = identityClaim()
  const raw = claims[idClaim]
  const id = typeof raw === 'string' && raw.trim() ? raw : String(claims.sub ?? '')
  return {
    id,
    email: typeof claims.email === 'string' ? claims.email : undefined,
    name: typeof claims.name === 'string' ? claims.name : undefined,
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // The mode is fixed for the lifetime of the bundle (build-time env).
  const mode = useRef(authMode()).current
  const [status, setStatus] = useState<AuthStatus>(
    mode === 'dev' ? 'authenticated' : 'loading',
  )
  const [user, setUser] = useState<AuthUser | null>(
    mode === 'dev' ? { id: 'dev' } : null,
  )

  // Pending silent-refresh timer, and a ref to the latest adoptSession so the
  // timer callback can re-adopt (and thereby reschedule) without adoptSession
  // depending on itself.
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const adoptRef = useRef<
    ((token: string, claims: Record<string, unknown>) => void) | null
  >(null)

  const clearRefreshTimer = useCallback(() => {
    if (refreshTimer.current !== null) {
      clearTimeout(refreshTimer.current)
      refreshTimer.current = null
    }
  }, [])

  const adoptSession = useCallback(
    (token: string, claims: Record<string, unknown>) => {
      tokenStore.setToken(token)
      setUser(userFromClaims(claims))
      setStatus('authenticated')

      // Schedule a silent refresh ~REFRESH_LEAD_SECONDS before expiry. Dev mode
      // never mints session JWTs, so it never schedules (finite exp required).
      clearRefreshTimer()
      const secs = secondsUntilExpiry(claims)
      if (!Number.isFinite(secs)) return
      const delay =
        Math.max(MIN_REFRESH_DELAY_SECONDS, secs - REFRESH_LEAD_SECONDS) * 1000
      refreshTimer.current = setTimeout(() => {
        void refreshSession(tokenStore.getToken() ?? '')
          .then((r) => adoptRef.current?.(r.token, r.claims))
          // On failure, do nothing: the token lapses and the next 401 drops the
          // session, exactly as today.
          .catch(() => {})
      }, delay)
    },
    [clearRefreshTimer],
  )
  adoptRef.current = adoptSession

  const dropSession = useCallback(() => {
    clearRefreshTimer()
    tokenStore.clearToken()
    if (mode === 'password') clearPersistedPasswordToken()
    setUser(null)
    setStatus('unauthenticated')
  }, [mode, clearRefreshTimer])

  // Boot: rehydrate an existing password session, if any.
  useEffect(() => {
    if (mode === 'dev') return
    const persisted = loadPersistedPasswordToken()
    if (persisted) adoptSession(persisted.token, persisted.claims)
    else setStatus('unauthenticated')
  }, [mode, adoptSession])

  // A 401 from api.ts means the API rejected the token: drop the session.
  useEffect(() => {
    if (mode === 'dev') return
    return tokenStore.onUnauthorized(dropSession)
  }, [mode, dropSession])

  // Cancel any pending silent-refresh timer when the provider unmounts.
  useEffect(() => clearRefreshTimer, [clearRefreshTimer])

  const submitCredentials = useCallback(
    async (email: string, password: string, register: boolean) => {
      const result = register
        ? await passwordRegister(email, password)
        : await passwordLogin(email, password)
      adoptSession(result.token, result.claims)
    },
    [adoptSession],
  )

  const logout = useCallback(() => {
    if (mode === 'dev') return
    dropSession()
  }, [mode, dropSession])

  const value = useMemo(
    () => ({
      mode,
      status,
      user,
      submitCredentials,
      logout,
    }),
    [mode, status, user, submitCredentials, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
