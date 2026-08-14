import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Sources from './Sources'
import type { SourceRef } from '../api'

function renderSources(sources: SourceRef[]) {
  return render(
    <MemoryRouter>
      <Sources sources={sources} />
    </MemoryRouter>,
  )
}

describe('Sources', () => {
  it('renders a compiled-from document with its source system', () => {
    renderSources([
      {
        kind: 'document',
        raw_document_id: 'rd-1',
        label: 'card-apply-workflow.md',
        source_system: 'manual_upload',
      },
    ])
    expect(screen.getByText(/Compiled from/i)).toBeInTheDocument()
    expect(screen.getByText(/card-apply-workflow\.md/)).toBeInTheDocument()
    expect(screen.getByText('manual_upload')).toBeInTheDocument()
  })

  it('renders a derived-from page as a link to the source page', () => {
    renderSources([{ kind: 'page', slug: 'api-rate-limiting', title: 'API Rate Limiting' }])
    expect(screen.getByText(/Derived from/i)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'API Rate Limiting' })
    expect(link).toHaveAttribute('href', '/items/api-rate-limiting')
  })

  it('renders nothing when there are no sources', () => {
    const { container } = renderSources([])
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a document without a source system (label only)', () => {
    renderSources([{ kind: 'document', raw_document_id: 'rd-2', label: 'notes.md' }])
    expect(screen.getByText(/Compiled from/i)).toBeInTheDocument()
    expect(screen.getByText(/notes\.md/)).toBeInTheDocument()
  })
})
