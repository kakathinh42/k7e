import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import GraphPage from './GraphPage'

vi.mock('../api', () => ({
  getGraph: vi.fn(),
  listSpaces: vi.fn(),
}))

import { getGraph, listSpaces } from '../api'

function renderGraphPage(initialEntry = '/graph') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <GraphPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('GraphPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listSpaces).mockResolvedValue([])
  })

  it('renders nodes and a cluster count from the graph', async () => {
    vi.mocked(getGraph).mockResolvedValue({
      nodes: [
        { id: '1', slug: 'page-a', title: 'Page A', degree: 1 },
        { id: '2', slug: 'page-b', title: 'Page B', degree: 1 },
        { id: '3', slug: 'lonely', title: 'Lonely', degree: 0 },
      ],
      edges: [
        { source: '1', target: '2', score: 0.8, relation: 'related', origin: 'vector' },
      ],
    })

    renderGraphPage()

    await waitFor(() => expect(screen.getByText('page-a')).toBeInTheDocument())
    expect(screen.getByText('page-b')).toBeInTheDocument()
    expect(screen.getByText('lonely')).toBeInTheDocument()
    // 3 nodes, 1 edge, 2 clusters ({a,b} and {lonely})
    expect(screen.getByText(/3 nodes · showing 1 of 1 links · 2 clusters/)).toBeInTheDocument()
  })

  it('shows an empty state when there are no pages', async () => {
    vi.mocked(getGraph).mockResolvedValue({ nodes: [], edges: [] })
    renderGraphPage()
    await waitFor(() =>
      expect(screen.getByText(/No published pages yet/)).toBeInTheDocument(),
    )
  })
})

describe('GraphPage space tabs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getGraph).mockResolvedValue({ nodes: [], edges: [] })
    vi.mocked(listSpaces).mockResolvedValue([
      { slug: 'me', name: 'Personal', kind: 'personal', item_count: 5 },
      { slug: 'engineering', name: 'Public', kind: 'public', item_count: 216 },
    ])
  })

  it('defaults to the whole graph (no space filter)', async () => {
    renderGraphPage()
    await waitFor(() => expect(getGraph).toHaveBeenCalledWith(0, undefined))
  })

  it('renders a tab per accessible space', async () => {
    renderGraphPage()
    expect(await screen.findByRole('button', { name: /Personal/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Public/ })).toBeInTheDocument()
  })

  it('clicking a space tab filters the graph to that space', async () => {
    renderGraphPage()
    fireEvent.click(await screen.findByRole('button', { name: /Personal/ }))
    await waitFor(() => expect(getGraph).toHaveBeenCalledWith(0, 'me'))
  })

  it('reads ?space= from the URL and filters to it', async () => {
    renderGraphPage('/graph?space=engineering')
    await waitFor(() => expect(getGraph).toHaveBeenCalledWith(0, 'engineering'))
  })

  it('shows a space-scoped empty state when a space has no pages', async () => {
    renderGraphPage('/graph?space=me')
    await waitFor(() =>
      expect(screen.getByText(/No pages in this space yet/)).toBeInTheDocument(),
    )
  })
})
