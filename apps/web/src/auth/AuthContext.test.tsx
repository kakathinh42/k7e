import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider, useAuth } from './AuthContext'
import * as tokenStore from './tokenStore'
import * as password from './password'

function fakeJwt(payload: Record<string, unknown>): string {
  const enc = (obj: unknown) =>
    btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${enc({ alg: 'RS256' })}.${enc(payload)}.sig`
}

function Probe() {
  const { mode, status, user } = useAuth()
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="status">{status}</span>
      <span data-testid="user">{user ? user.id : 'none'}</span>
    </div>
  )
}

function renderProbe() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('AuthProvider', () => {
  beforeEach(() => {
    sessionStorage.clear()
    tokenStore._resetForTests()
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    sessionStorage.clear()
  })

  it('dev mode is instantly authenticated as dev', () => {
    renderProbe()
    expect(screen.getByTestId('mode').textContent).toBe('dev')
    expect(screen.getByTestId('status').textContent).toBe('authenticated')
    expect(screen.getByTestId('user').textContent).toBe('dev')
  })

  it('password mode with no persisted token is unauthenticated', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'password')
    renderProbe()
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    )
    expect(screen.getByTestId('user').textContent).toBe('none')
  })

  it('password mode rehydrates a live persisted token into the tokenStore', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'password')
    const token = fakeJwt({ sub: 'alice', exp: Math.floor(Date.now() / 1000) + 600 })
    sessionStorage.setItem('llmwiki.auth.token', token)
    renderProbe()
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('authenticated'),
    )
    expect(screen.getByTestId('user').textContent).toBe('alice')
    expect(tokenStore.getToken()).toBe(token)
  })

  it('identity claim override picks the configured claim for user.id', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'password')
    vi.stubEnv('VITE_IDENTITY_CLAIM', 'email')
    const token = fakeJwt({
      sub: '00u123',
      email: 'alice@example.com',
      exp: Math.floor(Date.now() / 1000) + 600,
    })
    sessionStorage.setItem('llmwiki.auth.token', token)
    renderProbe()
    await waitFor(() =>
      expect(screen.getByTestId('user').textContent).toBe('alice@example.com'),
    )
  })

  it('a 401 signal drops the session', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'password')
    const token = fakeJwt({ sub: 'alice', exp: Math.floor(Date.now() / 1000) + 600 })
    sessionStorage.setItem('llmwiki.auth.token', token)
    renderProbe()
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('authenticated'),
    )
    tokenStore.notifyUnauthorized()
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    )
    expect(tokenStore.getToken()).toBeNull()
    expect(sessionStorage.getItem('llmwiki.auth.token')).toBeNull()
  })

  it('schedules a silent refresh before expiry and re-adopts the fresh token', async () => {
    vi.useFakeTimers()
    try {
      vi.stubEnv('VITE_AUTH_MODE', 'password')
      // exp ~120s out → schedule fires ~60s before, i.e. after ~60s.
      const nowSec = Math.floor(Date.now() / 1000)
      const token = fakeJwt({ sub: 'alice', exp: nowSec + 120 })
      const fresh = fakeJwt({ sub: 'alice', exp: nowSec + 8040 })
      sessionStorage.setItem('llmwiki.auth.token', token)

      const refreshSpy = vi
        .spyOn(password, 'refreshSession')
        .mockResolvedValue({ token: fresh, claims: { sub: 'alice', exp: nowSec + 8040 } })

      renderProbe()
      // let the boot effect adopt the persisted token
      await act(async () => {
        await Promise.resolve()
      })
      expect(screen.getByTestId('status').textContent).toBe('authenticated')
      expect(tokenStore.getToken()).toBe(token)

      // advance past the scheduled refresh point (~60s) and flush the resolved promise
      await act(async () => {
        vi.advanceTimersByTime(61_000)
        await Promise.resolve()
        await Promise.resolve()
      })

      expect(refreshSpy).toHaveBeenCalledTimes(1)
      expect(screen.getByTestId('status').textContent).toBe('authenticated')
      expect(tokenStore.getToken()).toBe(fresh)
    } finally {
      vi.useRealTimers()
      vi.restoreAllMocks()
    }
  })
})
