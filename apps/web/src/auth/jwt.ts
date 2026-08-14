/**
 * auth/jwt.ts — client-side JWT payload decoding for *display and routing
 * only*. The SPA never verifies signatures (it can't and needn't — the API
 * re-verifies every request); these claims must never gate anything
 * security-relevant beyond UI affordances.
 */

export function decodeJwtPayload(token: string): Record<string, unknown> {
  const parts = token.split('.')
  if (parts.length !== 3) throw new Error('not a JWT')
  const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
  const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
  const bytes = Uint8Array.from(atob(padded), (c) => c.charCodeAt(0))
  const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes))
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('JWT payload is not an object')
  }
  return parsed as Record<string, unknown>
}

/** True when the token's exp (seconds) is in the future. */
export function isUnexpired(claims: Record<string, unknown>): boolean {
  return typeof claims.exp === 'number' && claims.exp * 1000 > Date.now()
}

/**
 * Seconds from now until the token's `exp` (both in seconds). `Infinity` when
 * `exp` is absent or non-numeric — a token with no stated expiry never triggers
 * a proactive refresh.
 */
export function secondsUntilExpiry(claims: Record<string, unknown>): number {
  if (typeof claims.exp !== 'number') return Infinity
  return claims.exp - Date.now() / 1000
}
