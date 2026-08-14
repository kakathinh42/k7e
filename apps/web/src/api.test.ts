import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { listItems, search, getFacets, uploadDocument, ApiError } from './api'
import * as tokenStore from './auth/tokenStore'

function stubFetch(json: unknown, opts: { ok?: boolean; status?: number } = {}) {
  const f = vi.fn().mockResolvedValue({
    ok: opts.ok ?? true,
    status: opts.status ?? 200,
    statusText: 'Boom',
    json: () => Promise.resolve(json),
  })
  vi.stubGlobal('fetch', f)
  return f
}

function sentHeaders(f: ReturnType<typeof vi.fn>): Headers {
  return (f.mock.calls[0][1] as RequestInit).headers as Headers
}

describe('api classification params', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('listItems builds domain + type + repeated tag params', async () => {
    const f = stubFetch([])
    await listItems({ domain: 'backend', tags: ['redis', 'cache'], type: 'concept' })
    const url = f.mock.calls[0][0] as string
    expect(url).toContain('/items?')
    expect(url).toContain('domain=backend')
    expect(url).toContain('type=concept')
    expect(url).toContain('tag=redis')
    expect(url).toContain('tag=cache')
  })

  it('listItems with no args hits /items with no query string', async () => {
    const f = stubFetch([])
    await listItems()
    expect(f.mock.calls[0][0]).toMatch(/\/items$/)
  })

  it('search appends domain + tag to the query', async () => {
    const f = stubFetch({ hits: [] })
    await search('retry', { domain: 'backend', tags: ['redis'] })
    const url = f.mock.calls[0][0] as string
    expect(url).toContain('q=retry')
    expect(url).toContain('domain=backend')
    expect(url).toContain('tag=redis')
  })

  it('getFacets calls /facets and returns the payload', async () => {
    const payload = { domains: [{ value: 'backend', count: 2 }], tags: [], types: [] }
    stubFetch(payload)
    const facets = await getFacets()
    expect(facets).toEqual(payload)
  })

  it('uploadDocument appends space when given', async () => {
    const f = stubFetch({ workflow_id: 'wf', raw_document_id: 'rd' })
    await uploadDocument(new File(['# x'], 'x.md'), { space: 'personal' })
    const body = (f.mock.calls[0][1] as RequestInit).body as FormData
    expect(body.get('space')).toBe('personal')
  })

  it('uploadDocument omits space when not given', async () => {
    const f = stubFetch({ workflow_id: 'wf', raw_document_id: 'rd' })
    await uploadDocument(new File(['# x'], 'x.md'), {})
    const body = (f.mock.calls[0][1] as RequestInit).body as FormData
    expect(body.get('space')).toBeNull()
  })
})

describe('identity headers per auth mode', () => {
  beforeEach(() => tokenStore._resetForTests())
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  it('dev mode (default) sends X-User-* and no Authorization', async () => {
    const f = stubFetch([])
    await listItems()
    const headers = sentHeaders(f)
    expect(headers.get('X-User-Id')).toBe('dev')
    expect(headers.get('X-User-Roles')).toBe('reviewer')
    expect(headers.get('Authorization')).toBeNull()
  })

  it('password mode sends Bearer token and no X-User-*', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'password')
    tokenStore.setToken('tok-123')
    const f = stubFetch([])
    await listItems()
    const headers = sentHeaders(f)
    expect(headers.get('Authorization')).toBe('Bearer tok-123')
    expect(headers.get('X-User-Id')).toBeNull()
    expect(headers.get('X-User-Roles')).toBeNull()
  })

  it('password mode without a token sends neither identity header', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'password')
    const f = stubFetch([])
    await listItems()
    const headers = sentHeaders(f)
    expect(headers.get('Authorization')).toBeNull()
    expect(headers.get('X-User-Id')).toBeNull()
  })

  it('non-2xx throws ApiError with status and legacy message shape', async () => {
    stubFetch({}, { ok: false, status: 404 })
    const err = await listItems().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(404)
    expect(err.message.startsWith('HTTP 404')).toBe(true)
  })

  it('401 in bearer mode notifies unauthorized once (debounced)', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'password')
    tokenStore.setToken('tok-123')
    const seen = vi.fn()
    tokenStore.onUnauthorized(seen)
    stubFetch({}, { ok: false, status: 401 })
    await Promise.all([
      listItems().catch(() => {}),
      listItems().catch(() => {}),
      listItems().catch(() => {}),
    ])
    expect(seen).toHaveBeenCalledTimes(1)
  })

  it('401 in dev mode does NOT notify unauthorized', async () => {
    const seen = vi.fn()
    tokenStore.onUnauthorized(seen)
    stubFetch({}, { ok: false, status: 401 })
    await listItems().catch(() => {})
    expect(seen).not.toHaveBeenCalled()
  })
})
