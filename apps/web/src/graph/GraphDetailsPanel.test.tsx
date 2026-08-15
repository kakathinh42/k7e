import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import GraphDetailsPanel from './GraphDetailsPanel'
import type { GraphNode } from '../api'

const node: GraphNode = { id: '1', slug: 'page-a', title: 'Page A', degree: 5 }
const neighbor: GraphNode = { id: '2', slug: 'page-b', title: 'Page B', degree: 1 }

function props() {
  return {
    node,
    neighbors: [{ node: neighbor, origin: 'explicit', score: 0.9 }],
    pinned: false,
    onSelect: vi.fn(),
    onOpen: vi.fn(),
    onUnpin: vi.fn(),
    onClose: vi.fn(),
  }
}

describe('GraphDetailsPanel', () => {
  it('renders node title, slug, degree, and hub badge', () => {
    render(<GraphDetailsPanel {...props()} />)
    expect(screen.getByRole('heading', { name: 'Page A' })).toBeInTheDocument()
    expect(screen.getByText('page-a')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('Hub')).toBeInTheDocument()
  })

  it('lists neighbors', () => {
    render(<GraphDetailsPanel {...props()} />)
    expect(screen.getByRole('button', { name: /Page B/ })).toBeInTheDocument()
  })

  it('selects neighbor', () => {
    const p = props()
    render(<GraphDetailsPanel {...p} />)
    fireEvent.click(screen.getByRole('button', { name: /Page B/ }))
    expect(p.onSelect).toHaveBeenCalledWith('2')
  })

  it('opens item', () => {
    const p = props()
    render(<GraphDetailsPanel {...p} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open item' }))
    expect(p.onOpen).toHaveBeenCalledWith('page-a')
  })

  it('unpinned control calls onUnpin', () => {
    const p = props()
    render(<GraphDetailsPanel {...p} pinned />)
    fireEvent.click(screen.getByRole('button', { name: 'Unpin' }))
    expect(p.onUnpin).toHaveBeenCalledOnce()
  })

  it('close control calls onClose', () => {
    const p = props()
    render(<GraphDetailsPanel {...p} />)
    fireEvent.click(screen.getByRole('button', { name: 'Close details' }))
    expect(p.onClose).toHaveBeenCalledOnce()
  })

  it('renders nothing without node', () => {
    const p = props()
    const { container } = render(<GraphDetailsPanel {...p} node={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
