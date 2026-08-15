import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './AuthContext'
import RequireAuth from './RequireAuth'
import * as tokenStore from './tokenStore'

function renderGuarded(initialPath = '/teams/platform') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<div data-testid="login-page" />} />
          <Route
            path="/*"
            element={
              <RequireAuth>
                <div data-testid="protected" />
              </RequireAuth>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('RequireAuth', () => {
  beforeEach(() => {
    sessionStorage.clear()
    tokenStore._resetForTests()
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    sessionStorage.clear()
  })

  it('dev mode passes straight through', () => {
    renderGuarded()
    expect(screen.getByTestId('protected')).toBeInTheDocument()
  })

  it('unauthenticated password mode redirects to /login', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'password')
    renderGuarded()
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument())
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument()
  })
})
