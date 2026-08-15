import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import TeamDetailPage from './TeamDetailPage'

vi.mock('../api', () => ({
  getTeam: vi.fn(),
  addMember: vi.fn(),
  removeMember: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    mode: 'dev',
    status: 'authenticated',
    user: { id: 'dev' },
    logout: vi.fn(),
  }),
}))

import { getTeam, addMember, removeMember } from '../api'

function renderPage(slug = 'platform') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter initialEntries={[`/teams/${slug}`]}>
      <QueryClientProvider client={qc}>
        <Routes>
          <Route path="/teams/:slug" element={<TeamDetailPage />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

const OWNER_TEAM = {
  id: '1', slug: 'platform', name: 'Platform Team', org_id: 'o', space_id: 's',
  created_by: 'dev', created_at: '2026-07-02T00:00:00Z',
  members: [
    { user_id: 'dev', role: 'owner', created_at: '2026-07-02T00:00:00Z' },
    { user_id: 'alice', role: 'member', created_at: '2026-07-02T00:00:00Z' },
  ],
}

describe('TeamDetailPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders the members', async () => {
    vi.mocked(getTeam).mockResolvedValue(OWNER_TEAM)
    renderPage()
    await waitFor(() => expect(screen.getByText('Platform Team')).toBeInTheDocument())
    expect(screen.getByText('alice')).toBeInTheDocument()
  })

  it('shows admin controls to an owner', async () => {
    vi.mocked(getTeam).mockResolvedValue(OWNER_TEAM)
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /add member/i })).toBeInTheDocument(),
    )
  })

  it('hides admin controls from a non-admin member', async () => {
    vi.mocked(getTeam).mockResolvedValue({
      ...OWNER_TEAM,
      members: [
        { user_id: 'dev', role: 'member', created_at: '2026-07-02T00:00:00Z' },
        { user_id: 'alice', role: 'owner', created_at: '2026-07-02T00:00:00Z' },
      ],
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('Platform Team')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /add member/i })).not.toBeInTheDocument()
  })

  it('does not show a remove button on the current user own row', async () => {
    vi.mocked(getTeam).mockResolvedValue(OWNER_TEAM)
    renderPage()
    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument())
    // one Remove button (alice); none for dev (self).
    expect(screen.getAllByRole('button', { name: /remove/i })).toHaveLength(1)
  })

  it('adds a member', async () => {
    vi.mocked(getTeam).mockResolvedValue(OWNER_TEAM)
    vi.mocked(addMember).mockResolvedValue({
      user_id: 'bob', role: 'member', created_at: '2026-07-02T00:00:00Z',
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByLabelText('New member user id')).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByLabelText('New member user id'), { target: { value: 'bob' } })
    fireEvent.click(screen.getByRole('button', { name: /add member/i }))
    await waitFor(() => expect(addMember).toHaveBeenCalledWith('platform', 'bob', 'member'))
  })

  it('removes a member', async () => {
    vi.mocked(getTeam).mockResolvedValue(OWNER_TEAM)
    vi.mocked(removeMember).mockResolvedValue(undefined)
    renderPage()
    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /remove/i }))
    await waitFor(() => expect(removeMember).toHaveBeenCalledWith('platform', 'alice'))
  })

  it('shows a not-found state on 404', async () => {
    vi.mocked(getTeam).mockRejectedValue(new Error('HTTP 404: Not Found'))
    renderPage()
    await waitFor(() => expect(screen.getByText(/not a member/i)).toBeInTheDocument())
  })

  it('surfaces a mutation failure', async () => {
    vi.mocked(getTeam).mockResolvedValue(OWNER_TEAM)
    vi.mocked(removeMember).mockRejectedValue(new Error('HTTP 500: Internal Server Error'))
    renderPage()
    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /remove/i }))
    await waitFor(() => expect(screen.getByText(/HTTP 500/)).toBeInTheDocument())
  })

  it('shows feedback when adding with an empty user id', async () => {
    vi.mocked(getTeam).mockResolvedValue(OWNER_TEAM)
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /add member/i })).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: /add member/i }))
    await waitFor(() =>
      expect(screen.getByText('User ID is required.')).toBeInTheDocument(),
    )
    expect(addMember).not.toHaveBeenCalled()
  })
})
