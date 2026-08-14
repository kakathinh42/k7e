import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import TokensPage from './TokensPage'

vi.mock('../api', () => ({
  listPats: vi.fn(),
  createPat: vi.fn(),
  revokePat: vi.fn(),
}))

import { listPats, createPat, revokePat } from '../api'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <TokensPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('TokensPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the empty state when there are no tokens', async () => {
    vi.mocked(listPats).mockResolvedValue([])
    renderPage()
    await waitFor(() =>
      expect(screen.getByText(/No tokens yet/i)).toBeInTheDocument(),
    )
  })

  it('generates a token and shows the plaintext once', async () => {
    vi.mocked(listPats).mockResolvedValue([])
    vi.mocked(createPat).mockResolvedValue({
      id: '1',
      name: 'laptop',
      token: 'wpat_secret123',
      expires_at: null,
    })
    renderPage()
    fireEvent.change(screen.getByLabelText(/token name/i), {
      target: { value: 'laptop' },
    })
    fireEvent.click(screen.getByRole('button', { name: /generate token/i }))
    await waitFor(() => expect(createPat).toHaveBeenCalledWith('laptop'))
    await waitFor(() =>
      expect(screen.getByText('wpat_secret123')).toBeInTheDocument(),
    )
  })

  it('revokes a token', async () => {
    vi.mocked(listPats).mockResolvedValue([
      {
        id: 'abc',
        name: 'old',
        created_at: '2026-07-13T00:00:00Z',
        last_used_at: null,
        expires_at: null,
        revoked_at: null,
      },
    ])
    vi.mocked(revokePat).mockResolvedValue(undefined)
    renderPage()
    await waitFor(() => expect(screen.getByText('old')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /revoke/i }))
    await waitFor(() => expect(revokePat).toHaveBeenCalledWith('abc'))
  })
})
