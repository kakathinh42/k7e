/**
 * auth/config.ts — Auth mode + identity claim from Vite env.
 *
 * Exposed as functions (not module-top constants) so vitest can stub
 * `import.meta.env` per-test with `vi.stubEnv` — a module-top constant would
 * freeze the value at first import.
 *
 * Modes:
 * - `dev` (default): today's header seam (`X-User-Id: dev`), no login UI.
 * - `password`: native email + password login (self-issued session).
 */

export type AuthMode = 'dev' | 'password'

export function authMode(): AuthMode {
  return import.meta.env.VITE_AUTH_MODE === 'password' ? 'password' : 'dev'
}

/**
 * Claim used as the current user's id in the UI. Must mirror the API's
 * `jwt_identity_claim` so self-identity checks (e.g. team admin-gating)
 * compare like-for-like with `Membership.user_id`.
 */
export function identityClaim(): string {
  return import.meta.env.VITE_IDENTITY_CLAIM || 'sub'
}
