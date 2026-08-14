import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import StatusBadge from './StatusBadge'

describe('StatusBadge', () => {
  it('renders published with the published class and label', () => {
    render(<StatusBadge status="published" />)
    const el = screen.getByText('Published')
    expect(el).toHaveClass('badge', 'badge-published')
  })

  it('maps review gate decision to "In review"', () => {
    render(<StatusBadge status="review" />)
    expect(screen.getByText('In review')).toHaveClass('badge-review')
  })

  it('falls back to draft styling with a capitalized label for unknown status', () => {
    render(<StatusBadge status="weird" />)
    const el = screen.getByText('Weird')
    expect(el).toHaveClass('badge-draft')
  })
})
