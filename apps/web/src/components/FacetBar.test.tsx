import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import FacetBar from './FacetBar'
import type { Facets } from '../api'

const FACETS: Facets = {
  domains: [{ value: 'backend', count: 2 }, { value: 'frontend', count: 1 }],
  tags: [{ value: 'redis', count: 2 }],
  types: [{ value: 'source', count: 3 }],
}

function noop() {}

const base = {
  facets: FACETS,
  selected: { domain: undefined as string | undefined, tags: [] as string[], type: undefined as string | undefined },
  showType: true,
  onToggleDomain: noop,
  onToggleTag: noop,
  onToggleType: noop,
  onClear: noop,
}

describe('FacetBar', () => {
  it('renders domain, tags, and type groups with counts', () => {
    render(<FacetBar {...base} />)
    expect(screen.getByText('backend')).toBeInTheDocument()
    expect(screen.getByText('redis')).toBeInTheDocument()
    expect(screen.getByText('source')).toBeInTheDocument()
    expect(screen.getByText('domain')).toBeInTheDocument()
  })

  it('omits the type group when showType is false', () => {
    render(<FacetBar {...base} showType={false} />)
    expect(screen.queryByText('type')).not.toBeInTheDocument()
    expect(screen.queryByText('source')).not.toBeInTheDocument()
    expect(screen.getByText('backend')).toBeInTheDocument()
  })

  it('calls onToggleDomain with the clicked value', () => {
    const onToggleDomain = vi.fn()
    render(<FacetBar {...base} onToggleDomain={onToggleDomain} />)
    fireEvent.click(screen.getByRole('button', { name: /backend/ }))
    expect(onToggleDomain).toHaveBeenCalledWith('backend')
  })

  it('hides Clear when no filter is active and shows it when one is', () => {
    const { rerender } = render(<FacetBar {...base} />)
    expect(screen.queryByText(/clear/i)).not.toBeInTheDocument()
    rerender(<FacetBar {...base} selected={{ domain: 'backend', tags: [], type: undefined }} />)
    expect(screen.getByText(/clear/i)).toBeInTheDocument()
  })

  it('caps the tag list and expands/collapses with the "more" toggle', () => {
    const manyTags = Array.from({ length: 15 }, (_, i) => ({ value: `tag${i}`, count: 20 - i }))
    render(<FacetBar {...base} facets={{ ...FACETS, tags: manyTags }} />)
    // First 12 shown; the rest hidden behind "+3 more".
    expect(screen.getByText('tag0')).toBeInTheDocument()
    expect(screen.getByText('tag11')).toBeInTheDocument()
    expect(screen.queryByText('tag12')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /3 more/i }))
    expect(screen.getByText('tag14')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /show less/i }))
    expect(screen.queryByText('tag12')).not.toBeInTheDocument()
  })

  it('keeps a selected tag visible even when it is below the fold', () => {
    const manyTags = Array.from({ length: 15 }, (_, i) => ({ value: `tag${i}`, count: 20 - i }))
    render(
      <FacetBar
        {...base}
        facets={{ ...FACETS, tags: manyTags }}
        selected={{ domain: undefined, tags: ['tag14'], type: undefined }}
      />,
    )
    expect(screen.getByText('tag14')).toBeInTheDocument()
  })
})
