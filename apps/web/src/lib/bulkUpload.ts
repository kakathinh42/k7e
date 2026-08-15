import { getIngestStatus } from '../api'

/**
 * Run an async `step` over `items` strictly one at a time, in order: item `i+1`
 * never starts until item `i` has settled. A step that throws is swallowed here
 * (the step is expected to record its own failure) so one bad item never halts
 * the queue. This is what makes bulk ingest sequential — each document compiles
 * against the fully-committed prior ones.
 */
export async function runSequential<T>(
  items: readonly T[],
  step: (item: T, index: number) => Promise<void>,
): Promise<void> {
  for (let i = 0; i < items.length; i++) {
    try {
      await step(items[i], i)
    } catch {
      // Per-item failure is recorded by `step`; keep the queue moving.
    }
  }
}

/** Terminal ingest states — polling stops here. */
const TERMINAL = new Set(['done', 'failed'])

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Poll `GET /ingest/status/{id}` until the job reaches a terminal state
 * (`done` | `failed`) and return that state. `intervalMs` and `sleep` are
 * injectable so tests run without real timers. Returns `"failed"` if the job
 * never settles within `maxAttempts`.
 */
export async function pollIngestStatus(
  rawDocumentId: string,
  opts: {
    intervalMs?: number
    sleep?: (ms: number) => Promise<void>
    onStatus?: (status: string) => void
    maxAttempts?: number
  } = {},
): Promise<string> {
  const {
    intervalMs = 2500,
    sleep = defaultSleep,
    onStatus,
    // ~12.5 min ceiling: a normal .md compiles in well under a minute and now
    // resolves to `done` as soon as its IngestRun lands, so this only bounds a
    // genuinely stuck workflow (whose okf_ingest activity caps at 10 min).
    maxAttempts = 300,
  } = opts
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const { status } = await getIngestStatus(rawDocumentId)
    onStatus?.(status)
    if (TERMINAL.has(status)) return status
    await sleep(intervalMs)
  }
  return 'failed'
}
