import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import TeamsPage from './TeamsPage'

vi.mock('../api', () => ({ listTeams: vi.fn(), createTeam: vi.fn() }))

import { listTeams, createTeam } from '../api'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <TeamsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

const TEAM = {
  id: '1', slug: 'platform', name: 'Platform Team', org_id: 'o', space_id: 's',
  created_by: 'dev', created_at: '2026-07-02T00:00:00Z',
  members: [{ user_id: 'dev', role: 'owner', created_at: '2026-07-02T00:00:00Z' }],
}

describe('TeamsPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders the Teams heading', () => {
    vi.mocked(listTeams).mockResolvedValue([])
    renderPage()
    expect(screen.getByRole('heading', { name: 'Teams', level: 1 })).toBeInTheDocument()
  })

  it('shows the empty state when there are no teams', async () => {
    vi.mocked(listTeams).mockResolvedValue([])
    renderPage()
    await waitFor(() => expect(screen.getByText(/No teams yet/i)).toBeInTheDocument())
  })

  it('renders teams with a member count', async () => {
    vi.mocked(listTeams).mockResolvedValue([TEAM])
    renderPage()
    await waitFor(() => expect(screen.getByText('Platform Team')).toBeInTheDocument())
    expect(screen.getByText('1 member')).toBeInTheDocument()
  })

  it('submits a new team', async () => {
    vi.mocked(listTeams).mockResolvedValue([])
    vi.mocked(createTeam).mockResolvedValue({ ...TEAM, slug: 'payments', name: 'Payments' })
    renderPage()
    fireEvent.change(screen.getByLabelText('Team slug'), { target: { value: 'payments' } })
    fireEvent.change(screen.getByLabelText('Team name'), { target: { value: 'Payments' } })
    fireEvent.click(screen.getByRole('button', { name: /create team/i }))
    await waitFor(() => expect(createTeam).toHaveBeenCalledWith('payments', 'Payments'))
  })

  it('shows a slug-taken message on 409', async () => {
    vi.mocked(listTeams).mockResolvedValue([])
    vi.mocked(createTeam).mockRejectedValue(new Error('HTTP 409: Conflict'))
    renderPage()
    fireEvent.change(screen.getByLabelText('Team slug'), { target: { value: 'eng' } })
    fireEvent.change(screen.getByLabelText('Team name'), { target: { value: 'Engineering' } })
    fireEvent.click(screen.getByRole('button', { name: /create team/i }))
    await waitFor(() => expect(screen.getByText(/already taken/i)).toBeInTheDocument())
  })

  it('validates that slug and name are required', async () => {
    vi.mocked(listTeams).mockResolvedValue([])
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /create team/i }))
    await waitFor(() =>
      expect(screen.getByText(/Slug and name are required/i)).toBeInTheDocument(),
    )
    expect(createTeam).not.toHaveBeenCalled()
  })

  it('surfaces the real error message for non-409 failures', async () => {
    vi.mocked(listTeams).mockResolvedValue([])
    vi.mocked(createTeam).mockRejectedValue(new Error('HTTP 500: Internal Server Error'))
    renderPage()
    fireEvent.change(screen.getByLabelText('Team slug'), { target: { value: 'eng' } })
    fireEvent.change(screen.getByLabelText('Team name'), { target: { value: 'Engineering' } })
    fireEvent.click(screen.getByRole('button', { name: /create team/i }))
    await waitFor(() => expect(screen.getByText(/HTTP 500/)).toBeInTheDocument())
  })
})
