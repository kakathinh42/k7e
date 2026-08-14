import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import HomePage from './HomePage'

vi.mock('../api', () => ({
  listItems: vi.fn(),
  listSpaces: vi.fn(),
}))

import { listItems, listSpaces } from '../api'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <HomePage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

function src(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: '1', slug: 's1', title: 'A source', status: 'published',
    type: 'source', tags: [], updated_at: '2026-07-14T10:00:00Z',
    space: { slug: 'eng', name: 'Engineering', kind: 'public' },
    ...over,
  }
}

const SOURCE_ITEMS = [
  src({ id: '1', slug: 'maven', title: 'Maven Setup', space: { slug: 'eng', name: 'Engineering', kind: 'public' } }),
  src({ id: '2', slug: 'conv-a', title: 'Conversation A', space: { slug: 'me', name: 'Personal', kind: 'personal' } }),
  src({ id: '3', slug: 'conv-b', title: 'Conversation B', space: { slug: 'me', name: 'Personal', kind: 'personal' } }),
]

describe('HomePage (source-only dashboard)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listItems).mockResolvedValue(SOURCE_ITEMS as never)
    vi.mocked(listSpaces).mockResolvedValue([
      { slug: 'me', name: 'Personal', kind: 'personal', item_count: 11 },
      { slug: 'eng', name: 'Engineering', kind: 'public', item_count: 216 },
    ] as never)
  })

  it('counts only source ("main") pages, not the derived graph', async () => {
    renderPage()
    // The dashboard must query source pages only — never the full item set.
    await waitFor(() => expect(listItems).toHaveBeenCalledWith({ type: 'source' }))
    expect(vi.mocked(listItems).mock.calls.every(([arg]) => (arg as { type?: string })?.type === 'source')).toBe(true)
    // 3 source items → the stat reads 3, not the 227 all-types total.
    // (Both the Source-pages and Published cards read 3, hence findAll.)
    expect((await screen.findAllByText('3')).length).toBeGreaterThan(0)
    expect(screen.queryByText('227')).not.toBeInTheDocument()
    expect(await screen.findByText('Source pages')).toBeInTheDocument()
  })

  it('breaks the count down by space kind from the source items themselves', async () => {
    renderPage()
    // 2 personal + 1 public source → derived from item.space.kind, not the
    // all-types per-space counts (11 / 216).
    const breakdown = await screen.findByText(/private/)
    expect(breakdown.textContent).toContain('🔒 2 private')
    expect(breakdown.textContent).toContain('🌐 1 public')
    expect(breakdown.textContent).not.toContain('11')
    expect(breakdown.textContent).not.toContain('216')
  })

  it('lists source pages under Recent items', async () => {
    renderPage()
    expect(await screen.findByText('Maven Setup')).toBeInTheDocument()
    expect(screen.getByText('Conversation A')).toBeInTheDocument()
  })
})
