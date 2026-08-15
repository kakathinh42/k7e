import { useEffect, useImperativeHandle, useMemo, useRef, useState, type ForwardRefExoticComponent, type RefAttributes } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import type { GraphEdge, GraphNode } from '../api'
import { isHub, labelVisible, neighborSets, nodeRadius } from './graphView'

const EDGE_VECTOR = '#4a4a4a'
const EDGE_EXPLICIT = '#ff4d4d'
const NODE_DEFAULT = '#6e6e6e'
const NODE_HUB = '#c8c8c8'
const LABEL = '#d4d4d4'
const BG = '#0f0f0f'

type SimNode = GraphNode & { x?: number; y?: number; fx?: number | null; fy?: number | null }
type ForceGraphProps = Record<string, unknown>
const ForceGraph = ForceGraph2D as unknown as ForwardRefExoticComponent<ForceGraphProps & RefAttributes<GraphRef>>
type GraphRef = {
  centerAt: (x?: number, y?: number, ms?: number) => void
  zoom: {
    (): number | undefined
    (scale: number, ms?: number): void
  }
  zoomToFit: (ms?: number, padding?: number) => void
  d3ReheatSimulation: () => void
}

export interface GraphHandle {
  focusNode: (id: string) => void
  fitView: () => void
  resetView: () => void
  zoomBy: (factor: number) => void
}

export interface InteractiveGraphProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedId: string | null
  pinnedIds: ReadonlySet<string>
  onSelect: (id: string | null) => void
  onOpen: (slug: string) => void
  onPinsChange: (ids: Set<string>) => void
  ref?: React.Ref<GraphHandle>
}

export default function InteractiveGraph({
  nodes, edges, selectedId, pinnedIds, onSelect, onOpen, onPinsChange, ref,
}: InteractiveGraphProps) {
  const fgRef = useRef<GraphRef | null>(null)
  const canvasHolderRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)
  const nodeCache = useRef(new Map<string, SimNode>())
  const pinnedRef = useRef(new Map<string, { x: number; y: number }>())
  const hoverRef = useRef<string | null>(null)
  const lastClickRef = useRef<{ id: string; t: number } | null>(null)
  const adj = useMemo(() => neighborSets(nodes, edges), [nodes, edges])
  const adjRef = useRef(adj)
  adjRef.current = adj
  const pinKey = useMemo(() => Array.from(pinnedIds).sort().join(','), [pinnedIds])

  useEffect(() => {
    const holder = canvasHolderRef.current
    if (!holder) return
    setWidth(holder.clientWidth)
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(holder)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (pinnedRef.current.size === 0) return
    const staleIds = Array.from(pinnedRef.current.keys()).filter((id) => !pinnedIds.has(id))
    if (staleIds.length === 0) return
    for (const id of staleIds) {
      const node = nodeCache.current.get(id)
      if (node) {
        node.fx = null
        node.fy = null
      }
      pinnedRef.current.delete(id)
    }
    fgRef.current?.d3ReheatSimulation()
  }, [pinKey])

  const graphData = useMemo(() => ({
    nodes: nodes.map((node) => {
      const cached = nodeCache.current.get(node.id)
      if (cached) return cached
      const pinned = pinnedRef.current.get(node.id)
      const simNode: SimNode = { ...node, ...(pinned && { fx: pinned.x, fy: pinned.y }) }
      nodeCache.current.set(node.id, simNode)
      return simNode
    }),
    links: edges.map((edge) => ({ ...edge })),
  }), [nodes, edges])

  const fitView = () => fgRef.current?.zoomToFit(400, 40)
  const zoomBy = (factor: number) => {
    const graph = fgRef.current
    if (!graph) return
    const cur = graph.zoom() ?? 1
    graph.zoom(cur * factor, 400)
  }
  const resetView = () => {
    nodeCache.current.forEach((node) => { node.fx = undefined; node.fy = undefined })
    pinnedRef.current.clear()
    onPinsChange(new Set())
    const graph = fgRef.current
    if (!graph) return
    graph.d3ReheatSimulation()
    graph.zoomToFit(400, 40)
  }
  const focusNode = (id: string) => {
    const node = nodeCache.current.get(id)
    const graph = fgRef.current
    if (!node || !graph) return
    graph.centerAt(node.x, node.y, 400)
    graph.zoom(1.2, 400)
  }

  useImperativeHandle(ref, () => ({ focusNode, fitView, resetView, zoomBy }))

  const paint = (node: SimNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const hover = hoverRef.current
    const dimmed = hover && node.id !== hover && !adjRef.current.get(hover)?.has(node.id)
    ctx.globalAlpha = dimmed ? 0.15 : 1
    const radius = nodeRadius(node.degree)
    ctx.beginPath()
    ctx.arc(node.x ?? 0, node.y ?? 0, radius, 0, 2 * Math.PI)
    ctx.fillStyle = isHub(node.degree) ? NODE_HUB : NODE_DEFAULT
    ctx.fill()
    if (isHub(node.degree)) {
      ctx.strokeStyle = '#ffffff22'
      ctx.stroke()
    }
    if (node.id === selectedId) {
      ctx.beginPath()
      ctx.arc(node.x ?? 0, node.y ?? 0, radius + 2, 0, 2 * Math.PI)
      ctx.strokeStyle = '#ffffff'
      ctx.stroke()
    }
    if (labelVisible(node.degree, node.id === selectedId || node.id === hover, globalScale)) {
      ctx.font = `${12 / globalScale}px sans-serif`
      ctx.textAlign = 'left'
      ctx.textBaseline = 'middle'
      const x = (node.x ?? 0) + radius + 4
      const y = node.y ?? 0
      const width = ctx.measureText(node.slug).width
      ctx.fillStyle = 'rgba(15,15,15,0.75)'
      ctx.fillRect(x - 2, y - 8 / globalScale, width + 4, 16 / globalScale)
      ctx.fillStyle = LABEL
      ctx.fillText(node.slug, x, y)
    }
    ctx.globalAlpha = 1
  }

  return (
    <div style={{ position: 'relative' }}>
      <div ref={canvasHolderRef} style={{ height: 600 }} tabIndex={0} aria-label="Knowledge graph canvas" role="application">
        <ForceGraph
          ref={fgRef}
          graphData={graphData}
          backgroundColor={BG}
          nodeLabel={(node: SimNode) => `${node.title} · ${node.degree} link${node.degree !== 1 ? 's' : ''}`}
          linkColor={(edge: GraphEdge) => edge.origin === 'explicit' ? EDGE_EXPLICIT : EDGE_VECTOR}
          linkWidth={(edge: GraphEdge) => edge.origin === 'explicit' ? 1.5 : 1}
          onNodeClick={(node: SimNode) => {
            const now = Date.now()
            if (lastClickRef.current?.id === node.id && now - lastClickRef.current.t < 500) {
              lastClickRef.current = null
              onOpen(node.slug)
            } else {
              lastClickRef.current = { id: node.id, t: now }
            }
            onSelect(node.id)
          }}
          onBackgroundClick={() => onSelect(null)}
          onNodeDragEnd={(node: SimNode) => {
            node.fx = node.x
            node.fy = node.y
            if (node.x !== undefined && node.y !== undefined) pinnedRef.current.set(node.id, { x: node.x, y: node.y })
            onPinsChange(new Set(pinnedRef.current.keys()))
          }}
          onNodeHover={(node: SimNode | null) => {
            hoverRef.current = node?.id ?? null
          }}
          nodeCanvasObject={paint}
          nodePointerAreaPaint={(node: SimNode, color: string, ctx: CanvasRenderingContext2D) => {
            ctx.beginPath()
            ctx.arc(node.x ?? 0, node.y ?? 0, Math.max(nodeRadius(node.degree) + 4, 10), 0, 2 * Math.PI)
            ctx.fillStyle = color
            ctx.fill()
          }}
          cooldownTicks={300}
          minZoom={0.05}
          maxZoom={8}
          width={width || undefined}
          height={600}
        />
      </div>
      <div style={{ position: 'absolute', bottom: 8, left: 8 }}>
        <button aria-label="Zoom in" onClick={() => zoomBy(1.2)}>+</button>
        <button aria-label="Zoom out" onClick={() => zoomBy(0.8)}>−</button>
        <button aria-label="Fit view" onClick={fitView}>fit</button>
        <button aria-label="Reset view" onClick={resetView}>reset</button>
      </div>
    </div>
  )
}
