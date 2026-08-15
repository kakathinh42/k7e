/**
 * auth/password.ts — native email+password mode.
 *
 * Posts credentials to the k7e API (/api/auth/login | /api/auth/register,
 * proxied to the backend, prefix stripped) and receives a self-issued session
 * token — the SAME token the broker mode gets, so the rest of the app is
 * unchanged. Persists it in sessionStorage (rehydrated on boot). Claims are
 * decoded client-side for display only; the API re-verifies every request.
 */

import { decodeJwtPayload, isUnexpired } from './jwt'

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'
const TOKEN_KEY = 'llmwiki.auth.token'

export interface PasswordResult {
  token: string
  claims: Record<string, unknown>
}

async function _post(
  path: string,
  email: string,
  password: string,
): Promise<PasswordResult> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    throw new Error(
      res.status === 401 || res.status === 400 || res.status === 409
        ? 'invalid_credentials'
        : `auth_failed_${res.status}`,
    )
  }
  const { session_token: token } = (await res.json()) as { session_token: string }
  const claims = decodeJwtPayload(token)
  sessionStorage.setItem(TOKEN_KEY, token)
  return { token, claims }
}

export function passwordLogin(
  email: string,
  password: string,
): Promise<PasswordResult> {
  return _post('/auth/login', email, password)
}

export function passwordRegister(
  email: string,
  password: string,
): Promise<PasswordResult> {
  return _post('/auth/register', email, password)
}

/**
 * Silently re-mint the session before it expires. POSTs the current token as a
 * Bearer credential to /auth/refresh (no body); on success persists and returns
 * the fresh token. Throws `refresh_failed` on any non-2xx so the caller can let
 * the session lapse (the next 401 drops it, as today).
 */
export async function refreshSession(token: string): Promise<PasswordResult> {
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('refresh_failed')
  const { session_token: fresh } = (await res.json()) as { session_token: string }
  const claims = decodeJwtPayload(fresh)
  sessionStorage.setItem(TOKEN_KEY, fresh)
  return { token: fresh, claims }
}

/** Rehydrate an unexpired persisted token on boot; clears stale ones. */
export function loadPersistedToken(): PasswordResult | null {
  const token = sessionStorage.getItem(TOKEN_KEY)
  if (!token) return null
  try {
    const claims = decodeJwtPayload(token)
    if (isUnexpired(claims)) return { token, claims }
  } catch {
    // fall through to cleanup
  }
  sessionStorage.removeItem(TOKEN_KEY)
  return null
}

export function clearPersistedToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
}
