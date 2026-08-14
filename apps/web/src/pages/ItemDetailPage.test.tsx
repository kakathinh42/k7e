import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ItemDetailPage from './ItemDetailPage'

vi.mock('../api', () => ({ getItem: vi.fn() }))
import { getItem } from '../api'

function renderDetail() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter initialEntries={['/items/be-1']}>
      <QueryClientProvider client={qc}>
        <Routes>
          <Route path="/items/:slug" element={<ItemDetailPage />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

const DETAIL = {
  id: '1', slug: 'be-1', title: 'Backend One', status: 'published', type: 'source',
  domain: 'backend', tags: ['redis', 'cache'], updated_at: '2026-07-01T10:00:00Z',
  markdown_body: '# Body', version: 1, citations: [], model_id: 'm', sources: [],
}

describe('ItemDetailPage classification chips', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders domain + tag chips linking to the filtered browse', async () => {
    vi.mocked(getItem).mockResolvedValue(DETAIL as never)
    renderDetail()
    const domainLink = await screen.findByRole('link', { name: /backend/ })
    expect(domainLink).toHaveAttribute('href', '/items?domain=backend')
    expect(screen.getByRole('link', { name: /redis/ })).toHaveAttribute('href', '/items?tag=redis')
    expect(screen.getByRole('link', { name: /cache/ })).toHaveAttribute('href', '/items?tag=cache')
  })

  it('renders no domain chip when the item has no domain', async () => {
    vi.mocked(getItem).mockResolvedValue({ ...DETAIL, domain: null, tags: [] } as never)
    renderDetail()
    await waitFor(() => expect(screen.getByText('Backend One')).toBeInTheDocument())
    expect(screen.queryByRole('link', { name: /backend/ })).not.toBeInTheDocument()
  })
})
