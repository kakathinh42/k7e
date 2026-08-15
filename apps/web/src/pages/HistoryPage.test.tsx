import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import HistoryPage from './HistoryPage'

vi.mock('../api', () => ({
  getIngestHistory: vi.fn(),
  getEmbeddingStatus: vi.fn(),
}))

import { getIngestHistory, getEmbeddingStatus } from '../api'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <HistoryPage />
    </QueryClientProvider>,
  )
}

describe('HistoryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Existing tests don't assert on embeddings; give a benign default.
    vi.mocked(getEmbeddingStatus).mockResolvedValue({ total: 0, embedded: 0, pending: 0 } as never)
  })

  it('renders an upload row with tokens and cost', async () => {
    vi.mocked(getIngestHistory).mockResolvedValue([
      {
        id: '1',
        raw_document_id: 'rd-1',
        filename: 'meeting-notes.md',
        source_slug: 'meeting-notes',
        model_id: 'wiki-default',
        prompt_tokens: 2000,
        completion_tokens: 500,
        total_tokens: 2500,
        llm_calls: 3,
        cost_usd: 0.0135,
        page_count: 4,
        created_at: '2026-06-19T10:00:00Z',
      },
    ])

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('meeting-notes.md')).toBeInTheDocument()
      // Tokens + cost appear in both the summary card and the row -> at least one each.
      expect(screen.getAllByText('2,500').length).toBeGreaterThan(0)
      expect(screen.getAllByText('$0.0135').length).toBeGreaterThan(0)
    })
  })

  it('filters the table by space type and by month/year', async () => {
    vi.mocked(getIngestHistory).mockResolvedValue([
      {
        id: '1', raw_document_id: 'rd-1', filename: 'acme-roster.md', source_slug: null,
        model_id: 'wiki-default', prompt_tokens: 10, completion_tokens: 5, total_tokens: 15,
        llm_calls: 1, cost_usd: 0.001, page_count: 1, created_at: '2026-07-10T10:00:00Z',
        space: { slug: 'acme', name: 'Acme', kind: 'team' },
      },
      {
        id: '2', raw_document_id: 'rd-2', filename: 'my-private-note.md', source_slug: null,
        model_id: 'wiki-default', prompt_tokens: 20, completion_tokens: 5, total_tokens: 25,
        llm_calls: 1, cost_usd: 0.002, page_count: 1, created_at: '2026-06-05T10:00:00Z',
        space: { slug: 'user-me', name: 'My Space', kind: 'personal' },
      },
    ] as never)

    renderPage()
    await screen.findByText('acme-roster.md')
    // Both rows visible initially.
    expect(screen.getByText('my-private-note.md')).toBeInTheDocument()

    // Filter to Team → only the Acme row remains.
    fireEvent.click(screen.getByRole('button', { name: /Team/ }))
    await waitFor(() => {
      expect(screen.getByText('acme-roster.md')).toBeInTheDocument()
      expect(screen.queryByText('my-private-note.md')).not.toBeInTheDocument()
    })

    // Clear, then filter to June → only the personal (June) row remains.
    fireEvent.click(screen.getByRole('button', { name: /Clear filters/ }))
    fireEvent.change(screen.getByLabelText('Month'), { target: { value: '5' } }) // June (0-indexed)
    await waitFor(() => {
      expect(screen.getByText('my-private-note.md')).toBeInTheDocument()
      expect(screen.queryByText('acme-roster.md')).not.toBeInTheDocument()
    })
  })

  it('shows an empty state when there are no uploads', async () => {
    vi.mocked(getIngestHistory).mockResolvedValue([])
    renderPage()
    await waitFor(() =>
      expect(screen.getByText(/No uploads yet/i)).toBeInTheDocument(),
    )
  })

  it('shows "all embedded" when nothing is pending', async () => {
    vi.mocked(getIngestHistory).mockResolvedValue([])
    vi.mocked(getEmbeddingStatus).mockResolvedValue({ total: 241, embedded: 241, pending: 0 } as never)
    renderPage()
    expect(await screen.findByText('Embeddings')).toBeInTheDocument()
    expect(screen.getByText('241/241')).toBeInTheDocument()
    expect(screen.getByText(/all embedded/i)).toBeInTheDocument()
  })

  it('shows the pending count when embeddings are still running or failed', async () => {
    vi.mocked(getIngestHistory).mockResolvedValue([])
    vi.mocked(getEmbeddingStatus).mockResolvedValue({ total: 10, embedded: 7, pending: 3 } as never)
    renderPage()
    expect(await screen.findByText('7/10')).toBeInTheDocument()
    expect(screen.getByText(/3 pending/i)).toBeInTheDocument()
  })
})
