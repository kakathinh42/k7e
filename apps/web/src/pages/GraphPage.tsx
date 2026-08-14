import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getGraph, listSpaces, type GraphResponse, type Space } from '../api'
import {
  computeLayout,
  connectedComponents,
  degreeMap,
  LAYOUT_HEIGHT,
  LAYOUT_WIDTH,
} from '../lib/graphLayout'
import Skeleton from '../components/Skeleton'
import Alert from '../components/Alert'
import EmptyState from '../components/EmptyState'
import Button from '../components/Button'
import FilterChip from '../components/FilterChip'
import { SPACE_KIND_META } from '../components/SpaceBadge'

// Obsidian-style: single accent colour for explicit [[wikilink]] edges.
const EDGE_VECTOR  = '#4a4a4a'   // dark grey for vector similarity
const EDGE_EXPLICIT = '#ff4d4d'  // crimson for explicit wikilinks
const NODE_DEFAULT = '#6e6e6e'   // medium grey — Obsidian node colour
const NODE_HUB     = '#c8c8c8'   // light grey for highly-connected hubs
const LABEL_COLOR  = '#d4d4d4'   // near-white label text
const BG_COLOR     = '#0f0f0f'   // near-black canvas background

/** Obsidian-style node radius: small dots, larger for hubs. */
function nodeR(degree: number): number {
  // min 3 px (isolated), max 10 px (degree ≥ 12)
  return 3 + Math.min(degree, 12) * 0.58
}

/** Node fill: brighter for hubs (degree ≥ 5). */
function nodeColor(degree: number): string {
  return degree >= 5 ? NODE_HUB : NODE_DEFAULT
}

export default function GraphPage() {
  const navigate = useNavigate()
  const [minScore, setMinScore] = useState(0)
  const [params, setParams] = useSearchParams()
  const space = params.get('space') ?? undefined

  const setSpace = (slug: string | undefined) => {
    const next = new URLSearchParams(params)
    if (slug) next.set('space', slug)
    else next.delete('space')
    setParams(next)
  }

  const { data: spaces } = useQuery<Space[]>({ queryKey: ['spaces'], queryFn: () => listSpaces() })

  // Fetch once at min_score=0 (per space) and filter client-side so the slider
  // is instant. The space filter re-queries the backend for that space's graph.
  const { data, isLoading, error, refetch, isFetching } = useQuery<GraphResponse>({
    queryKey: ['graph', space],
    queryFn: () => getGraph(0, space),
  })

  const view = useMemo(() => {
    if (!data) return null
    const edges = data.edges.filter((e) => e.score >= minScore)
    const pos = computeLayout(data.nodes, edges)
    const comp = connectedComponents(data.nodes, edges)
    const deg = degreeMap(data.nodes, edges)
    const clusters = new Set(Object.values(comp)).size
    const nodeById = new Map(data.nodes.map((n) => [n.id, n.slug]))
    return { edges, pos, comp, deg, clusters, nodeById }
  }, [data, minScore])

  return (
    <main className="stack">
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
        <h1 style={{ marginRight: 'auto' }}>Knowledge Graph</h1>
        <label className="meta" htmlFor="min-score" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          Hide links weaker than
          <input
            id="min-score"
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            style={{ width: 120 }}
          />
          <span style={{ width: '2.5em' }}>{minScore.toFixed(2)}</span>
        </label>
        {minScore > 0 && (
          <Button variant="ghost" onClick={() => setMinScore(0)}>Show all</Button>
        )}
        <Button variant="secondary" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </Button>
      </div>

      {spaces && spaces.length > 1 && (
        <div className="space-tabs" role="tablist" aria-label="Filter graph by space">
          <FilterChip label="All" active={!space} onClick={() => setSpace(undefined)} />
          {spaces.map((s) => (
            <FilterChip
              key={s.slug}
              label={`${SPACE_KIND_META[s.kind]?.icon ?? ''} ${s.name}`}
              count={s.item_count}
              active={space === s.slug}
              onClick={() => setSpace(s.slug)}
            />
          ))}
        </div>
      )}

      <p className="meta">
        Pages are nodes; edges are links (grey = vector similarity, crimson = explicit{' '}
        <code>[[wikilink]]</code>). Hover an edge to see why two pages are linked.
        Click a node to open it.
      </p>

      {isLoading && <div className="card"><Skeleton width="80%" /></div>}
      {error && (
        <Alert>Error loading graph: {error instanceof Error ? error.message : 'Unknown error'}</Alert>
      )}
      {data && data.nodes.length === 0 && (
        <EmptyState>
          {space
            ? 'No pages in this space yet — pick another space or ingest a document here.'
            : 'No published pages yet — ingest a document to populate the graph.'}
        </EmptyState>
      )}

      {data && data.nodes.length > 0 && view && (
        <>
          <p className="meta">
            {data.nodes.length} nodes · showing {view.edges.length} of{' '}
            {data.edges.length} links · {view.clusters} clusters
            {view.edges.length < data.edges.length && (
              <> · <button className="btn btn-ghost" style={{ padding: '0 6px' }} onClick={() => setMinScore(0)}>show all links</button></>
            )}
          </p>

          {/* Dark canvas — matches Obsidian Graph View aesthetic */}
          <div
            className="card"
            style={{
              padding: 0,
              overflow: 'hidden',
              background: BG_COLOR,
              borderRadius: 'var(--radius-md)',
            }}
          >
            <svg
              role="img"
              aria-label="Knowledge graph"
              viewBox={`0 0 ${LAYOUT_WIDTH} ${LAYOUT_HEIGHT}`}
              style={{ width: '100%', height: 'auto', display: 'block' }}
            >
              {/* Background fill (in case card bg bleeds) */}
              <rect width={LAYOUT_WIDTH} height={LAYOUT_HEIGHT} fill={BG_COLOR} />

              {/* Edges — drawn first so nodes sit on top */}
              {view.edges.map((e, i) => {
                const a = view.pos[e.source]
                const b = view.pos[e.target]
                if (!a || !b) return null
                const explicit = e.origin === 'explicit'
                return (
                  <line
                    key={i}
                    x1={a.x}
                    y1={a.y}
                    x2={b.x}
                    y2={b.y}
                    stroke={explicit ? EDGE_EXPLICIT : EDGE_VECTOR}
                    strokeWidth={explicit ? 1.5 : 1}
                    strokeOpacity={explicit ? 0.9 : 0.55}
                  >
                    <title>{
                      explicit
                        ? `[[wikilink]] explicit · ${e.score.toFixed(3)}\n${view.nodeById.get(e.source) ?? e.source} → ${view.nodeById.get(e.target) ?? e.target}`
                        : `vector similarity · ${e.score.toFixed(3)}\n${view.nodeById.get(e.source) ?? e.source} ↔ ${view.nodeById.get(e.target) ?? e.target}`
                    }</title>
                  </line>
                )
              })}

              {/* Nodes + labels */}
              {data.nodes.map((n) => {
                const p = view.pos[n.id]
                if (!p) return null
                const deg = view.deg[n.id] ?? 0
                const r = nodeR(deg)
                const fill = nodeColor(deg)
                return (
                  <g
                    key={n.id}
                    transform={`translate(${p.x},${p.y})`}
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/items/${n.slug}`)}
                  >
                    <title>{`${n.title} · ${deg} link${deg !== 1 ? 's' : ''}`}</title>
                    {/* Invisible hit-area larger than the dot for easy clicking */}
                    <circle r={Math.max(r + 4, 10)} fill="transparent" />
                    {/* Visible dot */}
                    <circle
                      r={r}
                      fill={fill}
                      stroke={deg >= 5 ? '#ffffff22' : 'none'}
                      strokeWidth={1}
                    />
                    {/* Label — positioned to the right of the dot, same as Obsidian */}
                    <text
                      x={r + 4}
                      y={4}
                      fontSize={10}
                      fill={LABEL_COLOR}
                      style={{ pointerEvents: 'none', userSelect: 'none' }}
                    >
                      {n.slug}
                    </text>
                  </g>
                )
              })}
            </svg>
          </div>
        </>
      )}
    </main>
  )
}
