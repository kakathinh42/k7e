import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  passwordLogin,
  passwordRegister,
  loadPersistedToken,
  clearPersistedToken,
  refreshSession,
} from './password'

function fakeJwt(payload: Record<string, unknown>): string {
  const enc = (obj: unknown) =>
    btoa(JSON.stringify(obj))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '')
  return `${enc({ alg: 'HS256', typ: 'JWT' })}.${enc(payload)}.sig`
}

const FUTURE = Math.floor(Date.now() / 1000) + 3600

function stubFetch(ok: boolean, sessionToken: string, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => ({ session_token: sessionToken }),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('password auth', () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('passwordLogin POSTs /api/auth/login with credentials and returns token+claims', async () => {
    const tok = fakeJwt({ sub: 'alice@example.com', email: 'alice@example.com', exp: FUTURE })
    const f = stubFetch(true, tok)
    const res = await passwordLogin('alice@example.com', 'hunter2secret')
    expect(f).toHaveBeenCalledWith(
      '/api/auth/login',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({
      email: 'alice@example.com',
      password: 'hunter2secret',
    })
    expect(res.token).toBe(tok)
    expect(res.claims.sub).toBe('alice@example.com')
  })

  it('passwordRegister POSTs /api/auth/register', async () => {
    const tok = fakeJwt({ sub: 'bob@example.com', exp: FUTURE })
    const f = stubFetch(true, tok)
    await passwordRegister('bob@example.com', 'hunter2secret')
    expect(f).toHaveBeenCalledWith(
      '/api/auth/register',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('throws on a non-ok response (e.g. 401)', async () => {
    stubFetch(false, '', 401)
    await expect(passwordLogin('x@example.com', 'wrong')).rejects.toThrow()
  })

  it('persists then rehydrates an unexpired token; clear removes it', async () => {
    const tok = fakeJwt({ sub: 'alice@example.com', exp: FUTURE })
    stubFetch(true, tok)
    await passwordLogin('alice@example.com', 'hunter2secret')
    expect(loadPersistedToken()?.token).toBe(tok)
    clearPersistedToken()
    expect(loadPersistedToken()).toBeNull()
  })

  it('refreshSession POSTs /api/auth/refresh with the Bearer header and persists the new token', async () => {
    const fresh = fakeJwt({ sub: 'alice@example.com', exp: FUTURE })
    const f = stubFetch(true, fresh)
    const res = await refreshSession('old-token')
    expect(f).toHaveBeenCalledWith(
      '/api/auth/refresh',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer old-token' }),
      }),
    )
    expect(res.token).toBe(fresh)
    expect(res.claims.sub).toBe('alice@example.com')
    expect(sessionStorage.getItem('llmwiki.auth.token')).toBe(fresh)
  })

  it('refreshSession throws refresh_failed on a non-ok response', async () => {
    stubFetch(false, '', 401)
    await expect(refreshSession('old-token')).rejects.toThrow('refresh_failed')
  })
})
