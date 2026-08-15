import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from './LoginPage'

const { submitCredentials } = vi.hoisted(() => ({ submitCredentials: vi.fn() }))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    mode: 'password',
    status: 'unauthenticated',
    user: null,
    submitCredentials,
    logout: vi.fn(),
  }),
}))

function renderPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  )
}

describe('LoginPage — password mode', () => {
  beforeEach(() => {
    submitCredentials.mockReset()
    submitCredentials.mockResolvedValue(undefined)
  })

  it('renders the email+password form and submits login credentials', async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: 'alice@example.com' },
    })
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'hunter2secret' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))
    await waitFor(() =>
      expect(submitCredentials).toHaveBeenCalledWith(
        'alice@example.com',
        'hunter2secret',
        false,
      ),
    )
  })

  it('the register toggle submits with register=true', async () => {
    renderPage()
    fireEvent.click(
      screen.getByRole('button', { name: /register with your email/i }),
    )
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: 'bob@example.com' },
    })
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'hunter2secret' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^register$/i }))
    await waitFor(() =>
      expect(submitCredentials).toHaveBeenCalledWith(
        'bob@example.com',
        'hunter2secret',
        true,
      ),
    )
  })
})
