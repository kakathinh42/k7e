import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import ItemsPage from './ItemsPage'

vi.mock('../api', () => ({
  listItems: vi.fn(),
  search: vi.fn(),
  getFacets: vi.fn(),
}))

import { listItems, search, getFacets } from '../api'

function LocationSpy() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.search}</div>
}

function renderPage(initialEntry = '/items') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={qc}>
        <ItemsPage />
        <LocationSpy />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

const FACETS = {
  domains: [{ value: 'backend', count: 2 }, { value: 'frontend', count: 1 }],
  tags: [{ value: 'redis', count: 2 }, { value: 'cache', count: 1 }],
  types: [{ value: 'source', count: 3 }],
}

function item(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: '1', slug: 'be-1', title: 'Backend One', status: 'published',
    type: 'source', domain: 'backend', tags: ['redis'], updated_at: '2026-07-01T10:00:00Z',
    ...over,
  }
}

describe('ItemsPage (faceted browse)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getFacets).mockResolvedValue(FACETS as never)
    vi.mocked(listItems).mockResolvedValue([item()] as never)
    vi.mocked(search).mockResolvedValue({ hits: [] } as never)
  })

  it('renders the Browse heading and defaults to source ("main") pages', async () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'Browse', level: 1 })).toBeInTheDocument()
    // No ?type= in the URL → the Sources tab is the default, so the query is
    // pinned to source pages (one row per ingest, not the derived graph).
    await waitFor(() => expect(listItems).toHaveBeenCalledWith({ domain: undefined, tags: [], type: 'source', space: undefined }))
    expect(await screen.findByText('Backend One')).toBeInTheDocument()
  })

  it('reads filters from the URL and passes them to listItems (type still defaults to source)', async () => {
    renderPage('/items?domain=backend&tag=redis&tag=cache')
    await waitFor(() =>
      expect(listItems).toHaveBeenCalledWith({ domain: 'backend', tags: ['redis', 'cache'], type: 'source', space: undefined }),
    )
  })

  it('an explicit ?type= in the URL selects that type', async () => {
    renderPage('/items?type=concept')
    await waitFor(() =>
      expect(listItems).toHaveBeenCalledWith({ domain: undefined, tags: [], type: 'concept', space: undefined }),
    )
  })

  it('clicking the Concepts tab pins type=concept in the URL', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /concepts/i }))
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toContain('type=concept'))
    await waitFor(() =>
      expect(listItems).toHaveBeenCalledWith({ domain: undefined, tags: [], type: 'concept', space: undefined }),
    )
  })

  it('clicking the All tab shows every type (no type filter)', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'All' }))
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toContain('type=all'))
    // type=all is a sentinel → the browse query drops the type filter entirely.
    await waitFor(() =>
      expect(listItems).toHaveBeenCalledWith({ domain: undefined, tags: [], type: undefined, space: undefined }),
    )
  })

  it('clicking Sources from a non-default tab clears ?type= (clean default URL)', async () => {
    renderPage('/items?type=entity')
    fireEvent.click(await screen.findByRole('button', { name: /sources/i }))
    await waitFor(() => expect(screen.getByTestId('loc').textContent ?? '').not.toContain('type='))
  })

  it('hides the type tabs while a search query is active', async () => {
    renderPage('/items?q=retry')
    await waitFor(() => expect(search).toHaveBeenCalledWith('retry', { domain: undefined, tags: [], explain: false, space: undefined }))
    expect(screen.queryByRole('button', { name: /concepts/i })).not.toBeInTheDocument()
  })

  it('clicking a domain chip writes it to the URL', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /backend/ }))
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toContain('domain=backend'))
  })

  it('clicking a second tag chip ANDs it into the URL', async () => {
    renderPage('/items?tag=redis')
    fireEvent.click(await screen.findByRole('button', { name: /cache/ }))
    await waitFor(() => {
      const s = screen.getByTestId('loc').textContent ?? ''
      expect(s).toContain('tag=redis')
      expect(s).toContain('tag=cache')
    })
  })

  it('hides the type group while a search query is active', async () => {
    renderPage('/items?q=retry')
    await waitFor(() => expect(search).toHaveBeenCalledWith('retry', { domain: undefined, tags: [], explain: false, space: undefined }))
    expect(screen.queryByRole('button', { name: /source/ })).not.toBeInTheDocument()
  })

  it('shows the empty state when no items match', async () => {
    vi.mocked(listItems).mockResolvedValue([] as never)
    renderPage('/items?domain=frontend')
    expect(await screen.findByText(/no items match/i)).toBeInTheDocument()
  })

  it('Clear filters resets the facet params', async () => {
    renderPage('/items?domain=backend&tag=redis')
    fireEvent.click(await screen.findByText(/clear filters/i))
    await waitFor(() => {
      const s = screen.getByTestId('loc').textContent ?? ''
      expect(s).not.toContain('domain=')
      expect(s).not.toContain('tag=')
    })
  })

  it('shows a score breakdown when Explain is on and a hit has one', async () => {
    const hitBase = {
      id: 'h1', slug: 'points', title: 'Points expiry',
      snippet: 'Loyalty points expire after 12 months.', score: 1.234,
    }
    const breakdown = {
      total: 1.234, keyword: 0.5, vector: 0.7, recency: 0.9, importance: 0.1,
      weights: { keyword: 0.4, vector: 0.4, recency: 0.2, importance: 0.1 },
      expanded: false,
    }
    // Mirror the backend: a breakdown comes back only when explain is requested.
    vi.mocked(search).mockImplementation((_q, params) =>
      Promise.resolve({
        hits: [params?.explain ? { ...hitBase, breakdown } : hitBase],
      } as never),
    )

    renderPage('/items?q=points')

    // The hit renders, but no breakdown panel until Explain is toggled on.
    expect(await screen.findByText('Points expiry')).toBeInTheDocument()
    expect(screen.queryByTestId('score-breakdown')).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText(/explain/i))

    const panel = await screen.findByTestId('score-breakdown')
    expect(panel.textContent).toContain('keyword')
    expect(panel.textContent).toContain('1.234')
  })

  it('omits breakdown signals whose weight is zero (2-signal mode)', async () => {
    const hitBase = {
      id: 'h1', slug: 'points', title: 'Points expiry',
      snippet: 'points expire', score: 1.2,
    }
    const breakdown = {
      total: 1.2, keyword: 0.5, vector: 0.7, recency: 0.9, importance: 0.3,
      weights: { keyword: 1.0, vector: 1.0, recency: 0.0, importance: 0.0 },
      expanded: false,
    }
    vi.mocked(search).mockImplementation((_q, params) =>
      Promise.resolve({
        hits: [params?.explain ? { ...hitBase, breakdown } : hitBase],
      } as never),
    )

    renderPage('/items?q=points')
    fireEvent.click(await screen.findByLabelText(/explain/i))

    const panel = await screen.findByTestId('score-breakdown')
    expect(panel.textContent).toContain('keyword')
    expect(panel.textContent).toContain('vector')
    expect(panel.textContent).not.toContain('recency')
    expect(panel.textContent).not.toContain('importance')
  })
})
