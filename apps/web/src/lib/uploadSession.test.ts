import { describe, it, expect, beforeEach } from 'vitest'
import { saveJobs, loadJobs, STORAGE_KEY, type PersistedJob } from './uploadSession'

// The page's UploadJob shape (superset of PersistedJob) — includes the
// unserialisable `file` and transient statuses that must not persist.
interface UploadJobLike {
  id: string
  file?: unknown
  filename: string
  status: 'queued' | 'uploading' | 'compiling' | 'done' | 'failed'
  rawDocumentId?: string
  workflowId?: string
  error?: string
}

beforeEach(() => {
  sessionStorage.clear()
})

describe('uploadSession — saveJobs / loadJobs', () => {
  it('keeps only compiling/done/failed and drops queued/uploading; round-trips via loadJobs', () => {
    const jobs: UploadJobLike[] = [
      { id: 'a', file: {}, filename: 'a.md', status: 'queued' },
      { id: 'b', file: {}, filename: 'b.md', status: 'uploading' },
      { id: 'c', filename: 'c.md', status: 'compiling', rawDocumentId: 'r-c' },
      { id: 'd', filename: 'd.md', status: 'done', rawDocumentId: 'r-d', workflowId: 'w-d' },
      { id: 'e', filename: 'e.md', status: 'failed', error: 'boom' },
    ]
    saveJobs(jobs)
    const loaded = loadJobs()
    expect(loaded.map((j) => j.id)).toEqual(['c', 'd', 'e'])
    expect(loaded.map((j) => j.status)).toEqual(['compiling', 'done', 'failed'])
  })

  it('removes the key when there are no persistable jobs (loadJobs → [])', () => {
    const jobs: UploadJobLike[] = [
      { id: 'a', file: {}, filename: 'a.md', status: 'queued' },
      { id: 'b', file: {}, filename: 'b.md', status: 'uploading' },
    ]
    // Seed something first so we can prove removal happens.
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([{ id: 'x', filename: 'x', status: 'done' }]))
    saveJobs(jobs)
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
    expect(loadJobs()).toEqual([])
  })

  it('loadJobs returns [] on corrupt JSON', () => {
    sessionStorage.setItem(STORAGE_KEY, '{not json')
    expect(loadJobs()).toEqual([])
  })

  it('loadJobs returns [] on a non-array value', () => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ id: 'a', status: 'done' }))
    expect(loadJobs()).toEqual([])
  })

  it('loadJobs filters out entries missing id/filename or with an invalid status', () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { id: 'ok', filename: 'ok.md', status: 'done' },
        { id: 'no-status', filename: 'x.md', status: 'queued' }, // invalid persisted status
        { filename: 'no-id.md', status: 'done' },
        { id: 'no-filename', status: 'done' },
        { id: 42, filename: 'bad-id.md', status: 'done' }, // non-string id
      ]),
    )
    const loaded = loadJobs()
    expect(loaded.map((j) => j.id)).toEqual(['ok'])
  })

  it('persisted projection excludes file and includes id/filename/status/rawDocumentId/workflowId/error', () => {
    const jobs: UploadJobLike[] = [
      {
        id: 'j1',
        file: { fake: 'File' },
        filename: 'doc.md',
        status: 'done',
        rawDocumentId: 'raw-1',
        workflowId: 'wf-1',
        error: undefined,
      },
    ]
    saveJobs(jobs)
    const raw = JSON.parse(sessionStorage.getItem(STORAGE_KEY) as string) as PersistedJob[]
    expect(raw).toHaveLength(1)
    const entry = raw[0]
    expect(entry).not.toHaveProperty('file')
    expect(entry.id).toBe('j1')
    expect(entry.filename).toBe('doc.md')
    expect(entry.status).toBe('done')
    expect(entry.rawDocumentId).toBe('raw-1')
    expect(entry.workflowId).toBe('wf-1')
  })
})
