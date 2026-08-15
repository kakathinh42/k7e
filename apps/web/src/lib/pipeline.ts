export type StepState = 'done' | 'active' | 'pending'

export interface Step {
  key: string
  label: string
  sub?: string
  state: StepState
}

/** Outcome phases for an upload. The v2 OKF pipeline is autonomous — every
 *  source compiles into published pages, so there is no review/reject branch. */
export type UploadPhase = 'processing' | 'published'

/** Canonical v2 OKF ingest stages (load → redact → extract/compose/commit → mirror). */
const STAGES: { key: string; label: string; sub: string }[] = [
  { key: 'capture', label: 'Captured', sub: 'raw stored' },
  { key: 'redact', label: 'Redacted', sub: 'PII scrubbed' },
  { key: 'extract', label: 'Extracted', sub: 'typed pages' },
  { key: 'link', label: 'Linked', sub: '[[wikilinks]]' },
  { key: 'publish', label: 'Published', sub: 'searchable' },
]

export function buildUploadSteps(phase: UploadPhase): Step[] {
  if (phase === 'processing') {
    // Capture confirmed; the rest is the known pipeline shape (illustrative).
    return STAGES.map((s, i) => ({
      ...s,
      state: i === 0 ? 'done' : i === 2 ? 'active' : 'pending',
    }))
  }
  // Terminal phase: every stage done.
  return STAGES.map((s) => ({ ...s, state: 'done' }))
}

export interface UploadBaseline {
  itemSlugs: string[]
}

/** Heuristic, single-user-honest: detect THIS upload's outcome by diffing the
 *  item list against the snapshot taken at submit time. Racy under concurrent
 *  uploads — used only to advance the tracker, never as authoritative state. */
export function resolveUploadOutcome(
  baseline: UploadBaseline,
  currentItemSlugs: string[],
): UploadPhase {
  const newItem = currentItemSlugs.some((s) => !baseline.itemSlugs.includes(s))
  return newItem ? 'published' : 'processing'
}

export function buildProvenanceSteps(item: {
  status: string
  version: number
  model_id: string
}): Step[] {
  const finalLabel = item.status === 'published' ? 'Published' : 'Draft'
  return [
    { key: 'source', label: 'Source', sub: 'raw doc', state: 'done' },
    { key: 'compile', label: 'Compiled', sub: item.model_id, state: 'done' },
    { key: 'link', label: 'Linked', sub: '[[wikilinks]]', state: 'done' },
    { key: 'publish', label: finalLabel, sub: `v${item.version}`, state: 'done' },
  ]
}
