import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ItemRail from './ItemRail'
import type { Step } from '../lib/pipeline'
import type { SourceRef } from '../api'

const steps: Step[] = [
  { key: 'source', label: 'Source', sub: 'raw doc', state: 'done' },
  { key: 'publish', label: 'Published', sub: 'v3', state: 'done' },
]
const sources: SourceRef[] = [
  { kind: 'document', label: 'PgBouncer runbook', source_system: 'confluence' },
  { kind: 'page', slug: 'postgres-tuning', title: 'Postgres tuning' },
]

describe('ItemRail', () => {
  it('renders provenance steps and sources', () => {
    render(
      <MemoryRouter>
        <ItemRail steps={steps} sources={sources} />
      </MemoryRouter>,
    )
    expect(screen.getByText('Provenance')).toBeInTheDocument()
    expect(screen.getByText('Source')).toBeInTheDocument()
    expect(screen.getByText('Compiled from')).toBeInTheDocument()
    expect(screen.getByText(/PgBouncer runbook/)).toBeInTheDocument()
    expect(screen.getByText('Postgres tuning')).toBeInTheDocument()
  })

  it('omits the Sources section when there are no sources', () => {
    render(
      <MemoryRouter>
        <ItemRail steps={steps} sources={[]} />
      </MemoryRouter>,
    )
    expect(screen.queryByText('Sources')).not.toBeInTheDocument()
  })
})
