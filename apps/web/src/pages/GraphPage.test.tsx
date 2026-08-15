import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import GraphPage from './GraphPage'

const mockCaptured: { props: Record<string, unknown> } = { props: {} }
vi.mock('react-force-graph-2d', () => ({
  default: (props: Record<string, unknown>) => {
    mockCaptured.props = props
    return null
  },
}))

vi.mock('../api', () => ({
  getGraph: vi.fn(),
  listSpaces: vi.fn(),
}))

import { getGraph, listSpaces } from '../api'

function CurrentPath() {
  const location = useLocation()
  return <output data-testid="current-path">{location.pathname}</output>
}

function renderGraphPage(initialEntry = '/graph') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <GraphPage />
        <CurrentPath />
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

    await waitFor(() =>
      expect(screen.getByText(/3 nodes · showing 1 of 1 links · 2 clusters/)).toBeInTheDocument(),
    )
    const input = screen.getByLabelText('Search nodes')
    fireEvent.change(input, { target: { value: 'page-a' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByRole('heading', { name: 'Page A' })).toBeInTheDocument()
  })

  it('shows an empty state when there are no pages', async () => {
    vi.mocked(getGraph).mockResolvedValue({ nodes: [], edges: [] })
    renderGraphPage()
    await waitFor(() =>
      expect(screen.getByText(/No published pages yet/)).toBeInTheDocument(),
    )
  })

  it('filters slider client-side', async () => {
    vi.mocked(getGraph).mockResolvedValue({
      nodes: [{ id: '1', slug: 'page-a', title: 'Page A', degree: 0 }],
      edges: [],
    })
    renderGraphPage()
    await waitFor(() => expect(getGraph).toHaveBeenCalledWith(0, undefined))
    fireEvent.change(screen.getByRole('slider'), { target: { value: '0.5' } })
    expect(getGraph).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/1 nodes · showing 0 of 0 links/)).toBeInTheDocument()
  })

  it('reserves details column and renders selected aside inside it', async () => {
    vi.mocked(getGraph).mockResolvedValue({
      nodes: [{ id: '1', slug: 'page-a', title: 'Page A', degree: 0 }],
      edges: [],
    })
    renderGraphPage()

    const slot = await screen.findByTestId('graph-details-slot')
    expect(slot).toHaveStyle({ width: '280px', flexShrink: '0' })
    expect(slot.querySelector('aside')).toBeNull()

    const input = screen.getByLabelText('Search nodes')
    fireEvent.change(input, { target: { value: 'page-a' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(slot.querySelector('aside')).toHaveTextContent('Page A')
  })

  it('keeps selected node open after unpinning', async () => {
    vi.mocked(getGraph).mockResolvedValue({
      nodes: [{ id: '1', slug: 'page-a', title: 'Page A', degree: 0 }],
      edges: [],
    })
    renderGraphPage()
    const input = await screen.findByLabelText('Search nodes')
    fireEvent.change(input, { target: { value: 'page-a' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByRole('heading', { name: 'Page A' })).toBeInTheDocument()

    ;(mockCaptured.props.onNodeDragEnd as (node: { id: string; x: number; y: number }) => void)({ id: '1', x: 5, y: 6 })
    expect(await screen.findByRole('button', { name: 'Unpin' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Unpin' }))

    expect(screen.getByRole('heading', { name: 'Page A' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Unpin' })).not.toBeInTheDocument()
  })

  it('closes selected panel on Escape', async () => {
    vi.mocked(getGraph).mockResolvedValue({
      nodes: [{ id: '1', slug: 'page-a', title: 'Page A', degree: 0 }],
      edges: [],
    })
    renderGraphPage()
    const input = await screen.findByLabelText('Search nodes')
    fireEvent.change(input, { target: { value: 'page-a' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByRole('heading', { name: 'Page A' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('heading', { name: 'Page A' })).not.toBeInTheDocument()
  })

  it('keeps selection on Enter from search input and navigates on Enter from body', async () => {
    vi.mocked(getGraph).mockResolvedValue({
      nodes: [{ id: '1', slug: 'page-a', title: 'Page A', degree: 0 }],
      edges: [],
    })
    renderGraphPage()
    const input = await screen.findByLabelText('Search nodes')
    fireEvent.change(input, { target: { value: 'page-a' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByRole('heading', { name: 'Page A' })).toBeInTheDocument()
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByRole('heading', { name: 'Page A' })).toBeInTheDocument()
    expect(screen.getByTestId('current-path')).toHaveTextContent('/graph')

    fireEvent.keyDown(document.body, { key: 'Enter' })
    expect(screen.getByTestId('current-path')).toHaveTextContent('/items/page-a')
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
