import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import FilterChip from './FilterChip'

describe('FilterChip', () => {
  it('renders the label and count', () => {
    render(<FilterChip label="backend" count={12} active={false} onClick={() => {}} />)
    expect(screen.getByText('backend')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
  })

  it('reflects active state via aria-pressed', () => {
    render(<FilterChip label="backend" active onClick={() => {}} />)
    expect(screen.getByRole('button', { name: /backend/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('fires onClick when clicked', () => {
    const onClick = vi.fn()
    render(<FilterChip label="redis" active={false} onClick={onClick} />)
    fireEvent.click(screen.getByRole('button', { name: /redis/ }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('omits the count when not provided', () => {
    render(<FilterChip label="ops" active={false} onClick={() => {}} />)
    expect(screen.getByText('ops')).toBeInTheDocument()
  })
})
