import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getIngestHistory, getEmbeddingStatus, type IngestRun, type EmbeddingStatus } from '../api'
import Card from '../components/Card'
import Alert from '../components/Alert'
import Skeleton from '../components/Skeleton'
import EmptyState from '../components/EmptyState'
import FilterChip from '../components/FilterChip'
import SpaceBadge, { SPACE_KIND_META } from '../components/SpaceBadge'

type SpaceKind = 'personal' | 'team' | 'public'

const SPACE_KINDS: SpaceKind[] = ['personal', 'team', 'public']

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function fmtTokens(n: number): string {
  return n.toLocaleString()
}

function fmtCost(usd: number): string {
  // Per-ingest costs are tiny — keep 4 decimals below $0.10 so they stay meaningful.
  return usd < 0.1 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`
}

export default function HistoryPage() {
  const { data, isLoading, error } = useQuery<IngestRun[]>({
    queryKey: ['ingest-history'],
    queryFn: () => getIngestHistory(200),
    refetchInterval: 5000, // new uploads appear as they finish compiling
  })

  const [kind, setKind] = useState<SpaceKind | undefined>(undefined)
  const [year, setYear] = useState('') // '' = all years
  const [month, setMonth] = useState('') // '' = all months, else '0'..'11'

  // Embeddings are backfilled asynchronously, so poll: a stalled/failed
  // embedding shows up here as a non-zero "pending" count. Scoped to the same
  // filters as the table so the card reflects the current view (month is
  // 0-indexed in the UI → 1–12 for the API).
  const embedMonth = month !== '' ? Number(month) + 1 : undefined
  const embedYear = year !== '' ? Number(year) : undefined
  const embed = useQuery<EmbeddingStatus>({
    queryKey: ['embedding-status', kind, embedYear, embedMonth],
    queryFn: () => getEmbeddingStatus({ spaceKind: kind, year: embedYear, month: embedMonth }),
    refetchInterval: 5000,
  })

  const runs = useMemo(() => data ?? [], [data])

  // Distinct years present, newest first, for the Year dropdown.
  const years = useMemo(() => {
    const s = new Set<number>()
    for (const r of runs) s.add(new Date(r.created_at).getFullYear())
    return [...s].sort((a, b) => b - a)
  }, [runs])

  // Apply the date filters first; the space chips then show how many of that
  // date-scoped set fall in each space kind.
  const dateFiltered = useMemo(
    () =>
      runs.filter((r) => {
        const d = new Date(r.created_at)
        if (year && d.getFullYear() !== Number(year)) return false
        if (month !== '' && d.getMonth() !== Number(month)) return false
        return true
      }),
    [runs, year, month],
  )

  const kindCounts = useMemo(() => {
    const c: Record<SpaceKind, number> = { personal: 0, team: 0, public: 0 }
    for (const r of dateFiltered) {
      const k = r.space?.kind
      if (k === 'personal' || k === 'team' || k === 'public') c[k] += 1
    }
    return c
  }, [dateFiltered])

  const filtered = useMemo(
    () => dateFiltered.filter((r) => !kind || r.space?.kind === kind),
    [dateFiltered, kind],
  )

  const totalTokens = filtered.reduce((s, r) => s + r.total_tokens, 0)
  const totalCost = filtered.reduce((s, r) => s + r.cost_usd, 0)
  const anyFilter = Boolean(kind) || year !== '' || month !== ''

  return (
    <main className="stack">
      <h1>Upload History</h1>
      <p className="meta">
        Every ingested file, the tokens its compilation used, and the estimated cost.
      </p>

      {error && (
        <Alert>Error loading history: {error instanceof Error ? error.message : 'Unknown'}</Alert>
      )}

      {!isLoading && runs.length > 0 && (
        <Card>
          <div className="stack" style={{ gap: 'var(--space-3)' }}>
            <div className="space-tabs" role="tablist" aria-label="Filter by space type" style={{ marginBottom: 0 }}>
              <FilterChip label="All spaces" active={!kind} onClick={() => setKind(undefined)} />
              {SPACE_KINDS.map((k) => (
                <FilterChip
                  key={k}
                  label={`${SPACE_KIND_META[k].icon} ${SPACE_KIND_META[k].kindLabel}`}
                  count={kindCounts[k]}
                  active={kind === k}
                  onClick={() => setKind(kind === k ? undefined : k)}
                />
              ))}
            </div>
            <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
              <label className="meta" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                Month
                <select
                  className="input"
                  value={month}
                  onChange={(e) => setMonth(e.target.value)}
                  style={{ padding: '6px 10px' }}
                >
                  <option value="">All</option>
                  {MONTHS.map((m, i) => (
                    <option key={m} value={i}>{m}</option>
                  ))}
                </select>
              </label>
              <label className="meta" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                Year
                <select
                  className="input"
                  value={year}
                  onChange={(e) => setYear(e.target.value)}
                  style={{ padding: '6px 10px' }}
                >
                  <option value="">All</option>
                  {years.map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </label>
              {anyFilter && (
                <FilterChip
                  label="✕ Clear filters"
                  active={false}
                  onClick={() => {
                    setKind(undefined)
                    setYear('')
                    setMonth('')
                  }}
                />
              )}
            </div>
          </div>
        </Card>
      )}

      {!isLoading && filtered.length > 0 && (
        <div className="dashboard-grid">
          <Card>
            <div className="stat-value">{filtered.length}</div>
            <div className="stat-label">{anyFilter ? 'Uploads (filtered)' : 'Uploads'}</div>
          </Card>
          <Card>
            <div className="stat-value">{fmtTokens(totalTokens)}</div>
            <div className="stat-label">Total tokens</div>
          </Card>
          <Card>
            <div className="stat-value">{fmtCost(totalCost)}</div>
            <div className="stat-label">Total estimated cost</div>
          </Card>
        </div>
      )}

      {embed.data && embed.data.total > 0 && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <span className="stat-label">Embeddings{anyFilter ? ' (this view)' : ''}</span>
            <strong>{embed.data.embedded}/{embed.data.total}</strong>
            <span className="meta">
              {embed.data.pending === 0
                ? '✅ all embedded'
                : `⏳ ${embed.data.pending} pending`}
            </span>
          </div>
        </Card>
      )}

      <Card>
        {isLoading && <Skeleton width="70%" />}
        {!isLoading && runs.length === 0 && (
          <EmptyState>No uploads yet. Upload a document to see its compile cost here.</EmptyState>
        )}
        {!isLoading && runs.length > 0 && filtered.length === 0 && (
          <EmptyState>No uploads match these filters.</EmptyState>
        )}
        {filtered.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Space</th>
                  <th>When</th>
                  <th style={{ textAlign: 'right' }}>Pages</th>
                  <th style={{ textAlign: 'right' }}>LLM calls</th>
                  <th style={{ textAlign: 'right' }}>Input tok</th>
                  <th style={{ textAlign: 'right' }}>Output tok</th>
                  <th style={{ textAlign: 'right' }}>Total tok</th>
                  <th style={{ textAlign: 'right' }}>Cost</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <strong>{r.filename || r.source_slug || '(unnamed)'}</strong>
                      {r.source_slug && (
                        <div className="meta">{r.source_slug}</div>
                      )}
                    </td>
                    <td>
                      {r.space ? <SpaceBadge space={r.space} /> : <span className="meta">—</span>}
                    </td>
                    <td className="meta">{new Date(r.created_at).toLocaleString()}</td>
                    <td style={{ textAlign: 'right' }}>{r.page_count}</td>
                    <td style={{ textAlign: 'right' }}>{r.llm_calls}</td>
                    <td style={{ textAlign: 'right' }}>{fmtTokens(r.prompt_tokens)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtTokens(r.completion_tokens)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtTokens(r.total_tokens)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtCost(r.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="meta">
        Cost is estimated from the model's per-token price (configurable via
        LLM_COST_INPUT/OUTPUT_USD_PER_MTOK).
      </p>
    </main>
  )
}
