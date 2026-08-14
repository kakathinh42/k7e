import { describe, it, expect } from 'vitest'
import { secondsUntilExpiry } from './jwt'

describe('secondsUntilExpiry', () => {
  it('returns a positive value for a future exp', () => {
    const exp = Math.floor(Date.now() / 1000) + 600
    const secs = secondsUntilExpiry({ exp })
    expect(secs).toBeGreaterThan(590)
    expect(secs).toBeLessThanOrEqual(600)
  })

  it('returns a negative value for a past exp', () => {
    const exp = Math.floor(Date.now() / 1000) - 600
    expect(secondsUntilExpiry({ exp })).toBeLessThan(0)
  })

  it('returns Infinity when exp is absent', () => {
    expect(secondsUntilExpiry({})).toBe(Infinity)
  })

  it('returns Infinity when exp is non-numeric', () => {
    expect(secondsUntilExpiry({ exp: 'soon' })).toBe(Infinity)
  })
})
