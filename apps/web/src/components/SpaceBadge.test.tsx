import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import SpaceBadge from './SpaceBadge'

describe('SpaceBadge', () => {
  it('renders a personal space as Private with the personal class + name', () => {
    render(
      <SpaceBadge space={{ slug: 'user-x', name: 'Personal — x', kind: 'personal' }} />,
    )
    const el = screen.getByTitle(/Private/)
    expect(el).toHaveClass('badge', 'badge-space', 'badge-space-personal')
    expect(el).toHaveTextContent('Personal — x')
  })

  it('renders a public space with the public class', () => {
    render(
      <SpaceBadge space={{ slug: 'engineering', name: 'Engineering', kind: 'public' }} />,
    )
    expect(screen.getByTitle(/Public/)).toHaveClass('badge-space-public')
  })

  it('renders a team space with the team class', () => {
    render(<SpaceBadge space={{ slug: 'platform', name: 'Platform', kind: 'team' }} />)
    expect(screen.getByTitle(/Team/)).toHaveClass('badge-space-team')
  })

  it('shows the kind label instead of the name when showName is false', () => {
    render(
      <SpaceBadge
        space={{ slug: 'engineering', name: 'Engineering', kind: 'public' }}
        showName={false}
      />,
    )
    expect(screen.getByTitle(/Public/)).toHaveTextContent('Public')
    expect(screen.queryByText('Engineering')).not.toBeInTheDocument()
  })

  it('renders nothing for a null space', () => {
    const { container } = render(<SpaceBadge space={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
