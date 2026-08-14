import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ThemeToggle from './ThemeToggle'
import { applyTheme } from '../lib/theme'

describe('ThemeToggle', () => {
  beforeEach(() => {
    localStorage.clear()
    applyTheme('light')
  })

  it('toggles theme and persists on click', () => {
    render(<ThemeToggle />)
    fireEvent.click(screen.getByRole('button'))
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')
  })
})
