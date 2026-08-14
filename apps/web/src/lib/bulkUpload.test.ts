import { describe, it, expect, vi, beforeEach } from 'vitest'
import { runSequential, pollIngestStatus } from './bulkUpload'

vi.mock('../api', () => ({ getIngestStatus: vi.fn() }))
import { getIngestStatus } from '../api'

describe('runSequential', () => {
  it('runs items in order, one at a time (never overlapping)', async () => {
    const order: number[] = []
    let inFlight = 0
    let maxInFlight = 0
    await runSequential([0, 1, 2, 3], async (item) => {
      inFlight++
      maxInFlight = Math.max(maxInFlight, inFlight)
      await Promise.resolve()
      order.push(item)
      inFlight--
    })
    expect(order).toEqual([0, 1, 2, 3])
    expect(maxInFlight).toBe(1) // strictly sequential — never two at once
  })

  it('continues past a step that throws', async () => {
    const done: number[] = []
    await runSequential([0, 1, 2], async (item) => {
      if (item === 1) throw new Error('boom')
      done.push(item)
    })
    expect(done).toEqual([0, 2]) // item 1 failed, 0 and 2 still ran
  })
})

describe('pollIngestStatus', () => {
  beforeEach(() => vi.clearAllMocks())

  it('resolves once the job reaches a terminal state', async () => {
    vi.mocked(getIngestStatus)
      .mockResolvedValueOnce({ raw_document_id: 'r', status: 'received', workflow_id: 'w' })
      .mockResolvedValueOnce({ raw_document_id: 'r', status: 'processing', workflow_id: 'w' })
      .mockResolvedValueOnce({ raw_document_id: 'r', status: 'done', workflow_id: 'w' })
    const seen: string[] = []
    const status = await pollIngestStatus('r', {
      sleep: () => Promise.resolve(),
      onStatus: (s) => seen.push(s),
    })
    expect(status).toBe('done')
    expect(seen).toEqual(['received', 'processing', 'done'])
    expect(getIngestStatus).toHaveBeenCalledTimes(3)
  })

  it('returns failed when the job never settles', async () => {
    vi.mocked(getIngestStatus).mockResolvedValue({
      raw_document_id: 'r', status: 'processing', workflow_id: 'w',
    })
    const status = await pollIngestStatus('r', {
      sleep: () => Promise.resolve(),
      maxAttempts: 5,
    })
    expect(status).toBe('failed')
    expect(getIngestStatus).toHaveBeenCalledTimes(5)
  })
})
