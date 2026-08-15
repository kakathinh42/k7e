import { useState } from 'react'
import { currentTheme, toggleTheme, type Theme } from '../lib/theme'

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(currentTheme())
  return (
    <button
      type="button"
      className="btn btn-ghost"
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      onClick={() => setTheme(toggleTheme())}
    >
      {theme === 'dark' ? '☀︎' : '☾'}
    </button>
  )
}
