import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listItems, listSpaces, type ItemSummary, type Space } from '../api'
import PipelineStepper from '../components/PipelineStepper'
import StatusBadge from '../components/StatusBadge'
import SpaceBadge, { SPACE_KIND_META } from '../components/SpaceBadge'
import Card from '../components/Card'
import type { Step } from '../lib/pipeline'

/** "🔒 2 · 🌐 216" — source ("main") pages grouped by their space kind.
 * Derived from the items themselves (each carries its space), so the counts
 * match the source-only dashboard without a separate per-space query. */
function spaceBreakdown(items: ItemSummary[] | undefined): string {
  const byKind: Record<string, number> = {}
  for (const i of items ?? []) {
    const kind = i.space?.kind ?? 'public'
    byKind[kind] = (byKind[kind] ?? 0) + 1
  }
  return (['personal', 'team', 'public'] as const)
    .filter((k) => byKind[k])
    .map((k) => `${SPACE_KIND_META[k].icon} ${byKind[k]} ${SPACE_KIND_META[k].kindLabel.toLowerCase()}`)
    .join(' · ')
}

export default function HomePage() {
  // The dashboard is about "what did we ingest?" — source ("main") pages only,
  // never the derived concept/entity graph. Browse (the Items page) is where
  // the derived pages live, behind type tabs.
  const items = useQuery<ItemSummary[]>({
    queryKey: ['items', { type: 'source' }],
    queryFn: () => listItems({ type: 'source' }),
  })
  const spaces = useQuery<Space[]>({ queryKey: ['spaces'], queryFn: () => listSpaces() })

  const itemCount = items.data?.length ?? 0
  const publishedCount = items.data?.filter((i) => i.status === 'published').length ?? 0
  const breakdown = spaceBreakdown(items.data)

  const lifecycle: Step[] = [
    { key: 'capture', label: 'Capture', sub: 'sources', state: 'done' },
    { key: 'redact', label: 'Redact', sub: 'deterministic', state: 'done' },
    { key: 'extract', label: 'Extract', sub: 'typed pages', state: 'done' },
    { key: 'link', label: 'Link', sub: '[[wikilinks]]', state: 'done' },
    { key: 'publish', label: 'Publish', sub: `${publishedCount} live`, state: 'done' },
  ]

  return (
    <main className="stack">
      <h1>k7e</h1>
      <p className="meta">Compiled, citation-backed knowledge from your company sources.</p>

      <Card>
        <h2>How knowledge is compiled</h2>
        <PipelineStepper steps={lifecycle} ariaLabel="Ingestion lifecycle" />
      </Card>

      <div className="dashboard-grid">
        <Card>
          <div className="stat-value">{itemCount}</div>
          <div className="stat-label">Source pages</div>
          {breakdown && <div className="stat-breakdown">{breakdown}</div>}
        </Card>
        <Card>
          <div className="stat-value accent">{spaces.data?.length ?? 0}</div>
          <div className="stat-label">Spaces you can see</div>
          <div className="stat-breakdown">
            <Link to="/spaces" className="nav-link" style={{ padding: 0 }}>
              browse spaces →
            </Link>
          </div>
        </Card>
        <Card style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 'var(--space-3)' }}>
          <div className="stat-label" style={{ marginTop: 0 }}>Add knowledge</div>
          <Link className="btn btn-primary" to="/upload" style={{ textAlign: 'center' }}>Upload a document</Link>
        </Card>
      </div>

      <Card>
        <p className="label">Recent items</p>
        {items.isLoading && <p className="meta">Loading…</p>}
        {items.data && items.data.length === 0 && <p className="meta">No items yet.</p>}
        <div className="stack" style={{ marginTop: 'var(--space-3)' }}>
          {items.data?.slice(0, 5).map((item) => (
            <Link key={item.id} to={`/items/${item.slug}`} className="item-row">
              <span className="row-tag">{item.type}</span>
              <span className="row-title">{item.title}</span>
              <SpaceBadge space={item.space} />
              <StatusBadge status={item.status} />
            </Link>
          ))}
        </div>
      </Card>
    </main>
  )
}
