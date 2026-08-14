/**
 * auth/tokenStore.ts — framework-free bridge between the auth layer (React)
 * and `api.ts` (plain module; `request()` cannot use hooks).
 *
 * Holds the current Bearer token **in memory only** — persistence is owned by
 * `password` mode (its own sessionStorage key), which rehydrates this store on
 * boot. Also carries the 401 signal
 * from `request()` back to the AuthProvider, debounced so N parallel queries
 * hitting 401 produce a single re-login redirect.
 */

type Listener = () => void

let token: string | null = null
let listeners: Listener[] = []
let lastNotifiedAt = 0

const NOTIFY_DEBOUNCE_MS = 1000

export function getToken(): string | null {
  return token
}

export function setToken(value: string | null): void {
  token = value
}

export function clearToken(): void {
  token = null
}

/** Subscribe to unauthorized (401) signals; returns an unsubscribe fn. */
export function onUnauthorized(cb: Listener): () => void {
  listeners.push(cb)
  return () => {
    listeners = listeners.filter((l) => l !== cb)
  }
}

/** Fired by api.ts on a 401 in a non-dev mode. Debounced. */
export function notifyUnauthorized(): void {
  const now = Date.now()
  if (now - lastNotifiedAt < NOTIFY_DEBOUNCE_MS) return
  lastNotifiedAt = now
  for (const cb of [...listeners]) cb()
}

/** Test-only: reset module state between cases. */
export function _resetForTests(): void {
  token = null
  listeners = []
  lastNotifiedAt = 0
}
