/**
 * Persist the /upload session queue across a browser refresh.
 *
 * The page keeps its queue in React state, so a refresh wipes the visible
 * queue/history. We mirror the queue into `sessionStorage` (per-tab, cleared
 * when the tab closes) so a refresh rehydrates it and any still-`compiling`
 * job can resume polling. Only committed statuses are persisted — transient
 * `queued`/`uploading` jobs carry an unserialisable `File` and have no server
 * record yet, so re-uploading them on rehydrate would double-ingest.
 */

const STORAGE_KEY = 'llmwiki.upload.jobs'

/** Statuses worth persisting: a server record exists (or the attempt failed). */
type PersistedStatus = 'compiling' | 'done' | 'failed'

export interface PersistedJob {
  id: string
  filename: string
  status: PersistedStatus
  rawDocumentId?: string
  workflowId?: string
  error?: string
}

/** The subset of the page's UploadJob this module reads. */
interface JobLike {
  id: string
  filename: string
  status: string
  rawDocumentId?: string
  workflowId?: string
  error?: string
}

const PERSISTED_STATUSES: readonly PersistedStatus[] = ['compiling', 'done', 'failed']

function isPersistedStatus(s: unknown): s is PersistedStatus {
  return typeof s === 'string' && (PERSISTED_STATUSES as readonly string[]).includes(s)
}

/**
 * Persist the queue. Keeps only jobs whose status is `compiling|done|failed`
 * (drops transient `queued`/`uploading`, and the unserialisable `File`),
 * projecting each to the {@link PersistedJob} fields. Writes nothing and
 * removes the key when the kept list is empty.
 */
export function saveJobs(jobs: readonly JobLike[]): void {
  const list: PersistedJob[] = jobs
    .filter((j) => isPersistedStatus(j.status))
    .map((j) => ({
      id: j.id,
      filename: j.filename,
      status: j.status as PersistedStatus,
      rawDocumentId: j.rawDocumentId,
      workflowId: j.workflowId,
      error: j.error,
    }))
  if (list.length === 0) {
    sessionStorage.removeItem(STORAGE_KEY)
    return
  }
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(list))
}

/**
 * Read the persisted queue. Returns `[]` on a missing key, parse error, or a
 * non-array value, and drops any entry that doesn't look like a valid
 * {@link PersistedJob} (needs string `id` + `filename` and a valid status).
 */
export function loadJobs(): PersistedJob[] {
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (raw === null) return []
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return []
  }
  if (!Array.isArray(parsed)) return []
  return parsed.filter(
    (j): j is PersistedJob =>
      typeof j === 'object' &&
      j !== null &&
      typeof (j as PersistedJob).id === 'string' &&
      typeof (j as PersistedJob).filename === 'string' &&
      isPersistedStatus((j as PersistedJob).status),
  )
}

export { STORAGE_KEY }
