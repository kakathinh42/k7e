import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getGraph, listSpaces, type GraphResponse, type Space } from '../api'
import { connectedComponents, degreeMap, neighborSets } from '../graph/graphView'
import InteractiveGraph, { type GraphHandle } from '../graph/InteractiveGraph'
import GraphDetailsPanel from '../graph/GraphDetailsPanel'
import Skeleton from '../components/Skeleton'
import Alert from '../components/Alert'
import EmptyState from '../components/EmptyState'
import Button from '../components/Button'
import FilterChip from '../components/FilterChip'
import { SPACE_KIND_META } from '../components/SpaceBadge'

export default function GraphPage() {
  const navigate = useNavigate()
  const [minScore, setMinScore] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [pinnedIds, setPinnedIds] = useState(new Set<string>())
  const [search, setSearch] = useState('')
  const graphRef = useRef<GraphHandle | null>(null)
  const [params, setParams] = useSearchParams()
  const space = params.get('space') ?? undefined

  const setSpace = (slug: string | undefined) => {
    const next = new URLSearchParams(params)
    if (slug) next.set('space', slug)
    else next.delete('space')
    setParams(next)
  }

  const { data: spaces } = useQuery<Space[]>({ queryKey: ['spaces'], queryFn: () => listSpaces() })
  const { data, isLoading, error, refetch, isFetching } = useQuery<GraphResponse>({
    queryKey: ['graph', space],
    queryFn: () => getGraph(0, space),
  })

  // Edges memo must NOT depend on selectedId: a new array identity on every
  // selection would rebuild InteractiveGraph's graphData and reset the d3
  // simulation, drifting nodes away from under the pointer mid-interaction.
  const edges = useMemo(
    () => (data ? data.edges.filter((edge) => edge.score >= minScore) : []),
    [data, minScore],
  )

  const view = useMemo(() => {
    if (!data) return null
    const degrees = degreeMap(data.nodes, edges)
    const components = connectedComponents(data.nodes, edges)
    const nodeById = new Map(data.nodes.map((node) => [node.id, node]))
    const adjacency = neighborSets(data.nodes, edges)
    const selected = selectedId ? nodeById.get(selectedId) ?? null : null
    const neighbors = selectedId
      ? [...(adjacency.get(selectedId) ?? [])].flatMap((id) => {
          const node = nodeById.get(id)
          if (!node) return []
          const edge = edges
            .filter((candidate) =>
              (candidate.source === selectedId && candidate.target === id) ||
              (candidate.target === selectedId && candidate.source === id),
            )
            .sort((a, b) => Number(b.origin === 'explicit') - Number(a.origin === 'explicit') || b.score - a.score)[0]
          return edge ? [{ node, origin: edge.origin, score: edge.score }] : []
        })
      : []
    return {
      edges,
      degrees,
      clusters: new Set(Object.values(components)).size,
      selected,
      neighbors,
    }
  }, [data, edges, selectedId])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSelectedId(null)
        setSearch('')
        return
      }
      if (event.key !== 'Enter' || !selectedId) return
      const target = event.target as HTMLElement | null
      if (target?.matches('input, button')) return
      const node = data?.nodes.find((candidate) => candidate.id === selectedId)
      if (node) navigate(`/items/${node.slug}`)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [data, navigate, selectedId])

  const selectSearch = () => {
    const query = search.trim().toLowerCase()
    if (!query || !data) return
    const node = data.nodes.find((candidate) =>
      candidate.title.toLowerCase().includes(query) || candidate.slug.toLowerCase().includes(query),
    )
    if (!node) return
    setSelectedId(node.id)
    graphRef.current?.focusNode(node.id)
  }

  return (
    <main className="stack">
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
        <h1 style={{ marginRight: 'auto' }}>Knowledge Graph</h1>
        <label className="meta" htmlFor="min-score" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          Hide links weaker than
          <input id="min-score" type="range" min={0} max={1} step={0.01} value={minScore} onChange={(event) => setMinScore(Number(event.target.value))} style={{ width: 120 }} />
          <span style={{ width: '2.5em' }}>{minScore.toFixed(2)}</span>
        </label>
        {minScore > 0 && <Button variant="ghost" onClick={() => setMinScore(0)}>Show all</Button>}
        <Button variant="secondary" onClick={() => refetch()} disabled={isFetching}>{isFetching ? 'Refreshing…' : 'Refresh'}</Button>
      </div>

      {spaces && spaces.length > 1 && (
        <div className="space-tabs" role="tablist" aria-label="Filter graph by space">
          <FilterChip label="All" active={!space} onClick={() => setSpace(undefined)} />
          {spaces.map((item) => <FilterChip key={item.slug} label={`${SPACE_KIND_META[item.kind]?.icon ?? ''} ${item.name}`} count={item.item_count} active={space === item.slug} onClick={() => setSpace(item.slug)} />)}
        </div>
      )}

      <p className="meta">Pages are nodes; edges are links (grey = vector similarity, crimson = explicit <code>[[wikilink]]</code>). Drag to pin · double-click opens · hover highlights neighbours</p>
      {isLoading && <div className="card"><Skeleton width="80%" /></div>}
      {error && <Alert>Error loading graph: {error instanceof Error ? error.message : 'Unknown error'}</Alert>}
      {data && data.nodes.length === 0 && <EmptyState>{space ? 'No pages in this space yet — pick another space or ingest a document here.' : 'No published pages yet — ingest a document to populate the graph.'}</EmptyState>}

      {data && data.nodes.length > 0 && view && (
        <>
          <p className="meta">{data.nodes.length} nodes · showing {view.edges.length} of {data.edges.length} links · {view.clusters} clusters{view.edges.length < data.edges.length && <> · <button className="btn btn-ghost" style={{ padding: '0 6px' }} onClick={() => setMinScore(0)}>show all links</button></>}</p>
          <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <input aria-label="Search nodes" value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') selectSearch() }} />
              {search && !data.nodes.some((node) => node.title.toLowerCase().includes(search.toLowerCase()) || node.slug.toLowerCase().includes(search.toLowerCase())) && <p role="status">No matches</p>}
              <div className="card" style={{ padding: 0, overflow: 'hidden', background: '#0f0f0f', borderRadius: 'var(--radius-md)' }}>
                <InteractiveGraph ref={graphRef} nodes={data.nodes} edges={view.edges} selectedId={selectedId} pinnedIds={pinnedIds} onSelect={setSelectedId} onOpen={(slug) => navigate(`/items/${slug}`)} onPinsChange={setPinnedIds} />
              </div>
            </div>
            <div data-testid="graph-details-slot" style={{ width: 280, flexShrink: 0 }}>
              <GraphDetailsPanel node={view.selected} neighbors={view.neighbors} pinned={selectedId ? pinnedIds.has(selectedId) : false} onSelect={setSelectedId} onOpen={(slug) => navigate(`/items/${slug}`)} onUnpin={() => selectedId && setPinnedIds((ids) => { const next = new Set(ids); next.delete(selectedId); return next })} onClose={() => setSelectedId(null)} />
            </div>
          </div>
        </>
      )}
    </main>
  )
}
