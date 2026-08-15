import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PipelineStepper from './PipelineStepper'
import type { Step } from '../lib/pipeline'

const steps: Step[] = [
  { key: 'a', label: 'Captured', state: 'done' },
  { key: 'b', label: 'Interpreted', state: 'active' },
  { key: 'c', label: 'Published', state: 'pending' },
]

describe('PipelineStepper', () => {
  it('renders all step labels', () => {
    render(<PipelineStepper steps={steps} />)
    expect(screen.getByText('Captured')).toBeInTheDocument()
    expect(screen.getByText('Published')).toBeInTheDocument()
  })

  it('marks the active step with aria-current', () => {
    render(<PipelineStepper steps={steps} />)
    const active = screen.getByText('Interpreted').closest('li')
    expect(active).toHaveAttribute('aria-current', 'step')
  })

  it('applies the vertical modifier class when variant is vertical', () => {
    const { container } = render(<PipelineStepper steps={steps} variant="vertical" />)
    expect(container.querySelector('ol')).toHaveClass('stepper-vertical')
  })
})
