import { describe, it, expect } from 'vitest'
import {
  buildUploadSteps,
  buildProvenanceSteps,
  resolveUploadOutcome,
} from './pipeline'

describe('buildUploadSteps', () => {
  it('marks capture done and one step active while processing', () => {
    const steps = buildUploadSteps('processing')
    expect(steps[0].state).toBe('done')
    expect(steps.some((s) => s.state === 'active')).toBe(true)
    expect(steps[steps.length - 1].state).toBe('pending')
  })

  it('marks every step done on publish', () => {
    const steps = buildUploadSteps('published')
    expect(steps.every((s) => s.state === 'done')).toBe(true)
    expect(steps[steps.length - 1].label).toBe('Published')
  })
})

describe('resolveUploadOutcome', () => {
  const baseline = { itemSlugs: ['a'] }

  it('returns published when a new item slug appears', () => {
    expect(resolveUploadOutcome(baseline, ['a', 'b'])).toBe('published')
  })

  it('returns processing when nothing new appeared', () => {
    expect(resolveUploadOutcome(baseline, ['a'])).toBe('processing')
  })
})

describe('buildProvenanceSteps', () => {
  it('builds four done steps ending in the item status', () => {
    const steps = buildProvenanceSteps({
      status: 'published',
      version: 3,
      model_id: 'wiki-default',
    })
    expect(steps).toHaveLength(4)
    expect(steps.every((s) => s.state === 'done')).toBe(true)
    expect(steps[1].sub).toBe('wiki-default')
    expect(steps[3].label).toBe('Published')
  })
})
