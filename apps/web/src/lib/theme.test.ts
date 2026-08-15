import { describe, it, expect, beforeEach } from 'vitest'
import { getInitialTheme, applyTheme, toggleTheme } from './theme'

describe('theme helpers', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('getInitialTheme returns the stored value when present', () => {
    localStorage.setItem('theme', 'light')
    expect(getInitialTheme()).toBe('light')
  })

  it('getInitialTheme defaults to dark when nothing is stored', () => {
    expect(getInitialTheme()).toBe('dark')
  })

  it('applyTheme sets data-theme and persists', () => {
    applyTheme('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')
  })

  it('toggleTheme flips dark to light and returns the new value', () => {
    applyTheme('dark')
    expect(toggleTheme()).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })
})
