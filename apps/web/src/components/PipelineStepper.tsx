import type { Step } from '../lib/pipeline'

export default function PipelineStepper({
  steps,
  ariaLabel = 'Pipeline progress',
  variant = 'horizontal',
}: {
  steps: Step[]
  ariaLabel?: string
  variant?: 'horizontal' | 'vertical'
}) {
  return (
    <ol
      className={`stepper ${variant === 'vertical' ? 'stepper-vertical' : ''}`.trim()}
      aria-label={ariaLabel}
    >
      {steps.map((step, i) => (
        <li
          key={step.key}
          className={`stepper-step ${step.state}`}
          aria-current={step.state === 'active' ? 'step' : undefined}
        >
          <span className="stepper-dot">{step.state === 'done' ? '✓' : i + 1}</span>
          <span className="stepper-text">
            <span className="stepper-name">{step.label}</span>
            {step.sub && <span className="stepper-sub">{step.sub}</span>}
          </span>
        </li>
      ))}
    </ol>
  )
}
