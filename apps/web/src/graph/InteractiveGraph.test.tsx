import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import InteractiveGraph, { type GraphHandle } from './InteractiveGraph'
import type { GraphEdge, GraphNode } from '../api'

const mockCaptured: { props: Record<string, unknown> } = { props: {} }
const mockGraph = {
  zoom: vi.fn(() => 2),
  centerAt: vi.fn(),
  zoomToFit: vi.fn(),
  d3ReheatSimulation: vi.fn(),
}
vi.mock('react-force-graph-2d', () => ({
  default: (props: Record<string, any>) => {
    if (props.ref && typeof props.ref === 'object') props.ref.current = mockGraph
    mockCaptured.props = props
    return null
  },
}))

const nodes: GraphNode[] = [
  { id: '1', slug: 'a', title: 'A', degree: 1 },
  { id: '2', slug: 'hub', title: 'Hub', degree: 6 },
]
const edges: GraphEdge[] = [
  { source: '1', target: '2', score: 0.5, relation: 'related', origin: 'vector' },
]

function props() {
  return {
    nodes,
    edges,
    selectedId: null,
    pinnedIds: new Set<string>(),
    onSelect: vi.fn(),
    onOpen: vi.fn(),
    onPinsChange: vi.fn(),
  }
}

class MockResizeObserver {
  static instances: MockResizeObserver[] = []
  constructor(private readonly callback: ResizeObserverCallback) {
    MockResizeObserver.instances.push(this)
  }
  observe() {}
  disconnect() {}
  trigger(width: number) {
    this.callback([{ contentRect: { width } } as ResizeObserverEntry], this as unknown as ResizeObserver)
  }
}

describe('InteractiveGraph', () => {
  beforeEach(() => {
    MockResizeObserver.instances = []
    vi.stubGlobal('ResizeObserver', MockResizeObserver)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('passes measured holder width to ForceGraph', () => {
    render(<InteractiveGraph {...props()} />)

    act(() => MockResizeObserver.instances[0].trigger(615))

    expect(mockCaptured.props.width).toBe(615)
  })

  it('mounts with nodes and copied id links', () => {
    render(<InteractiveGraph {...props()} />)
    const graphData = mockCaptured.props.graphData as { nodes: GraphNode[]; links: GraphEdge[] }
    expect(graphData.nodes).toHaveLength(2)
    expect(graphData.links).toEqual(edges)
    expect(graphData.links[0]).not.toBe(edges[0])
    expect(graphData.links[0]).toMatchObject({
      source: '1', target: '2', score: 0.5, origin: 'vector',
    })
  })

  it('wires node and background selection', () => {
    const p = props()
    render(<InteractiveGraph {...p} />)
    ;(mockCaptured.props.onNodeClick as (node: { id: string }) => void)({ id: '1' })
    ;(mockCaptured.props.onBackgroundClick as () => void)()
    expect(p.onSelect).toHaveBeenNthCalledWith(1, '1')
    expect(p.onSelect).toHaveBeenNthCalledWith(2, null)
  })

  it('opens node after two clicks within 500ms', () => {
    const now = vi.spyOn(Date, 'now').mockReturnValueOnce(1_000).mockReturnValueOnce(1_450)
    const p = props()
    render(<InteractiveGraph {...p} />)
    const onNodeClick = mockCaptured.props.onNodeClick as (node: { id: string; slug: string }) => void
    onNodeClick({ id: '1', slug: 'a' })
    onNodeClick({ id: '1', slug: 'a' })
    expect(p.onOpen).toHaveBeenCalledOnce()
    expect(p.onOpen).toHaveBeenCalledWith('a')
    now.mockRestore()
  })

  it('selects node on a single click', () => {
    const p = props()
    render(<InteractiveGraph {...p} />)
    ;(mockCaptured.props.onNodeClick as (node: { id: string; slug: string }) => void)({ id: '1', slug: 'a' })
    expect(p.onSelect).toHaveBeenCalledOnce()
    expect(p.onOpen).not.toHaveBeenCalled()
  })

  it('handles node hover without calling refresh on graph ref', () => {
    render(<InteractiveGraph {...props()} />)
    const onNodeHover = mockCaptured.props.onNodeHover as (node: { id: string } | null) => void
    expect(() => onNodeHover({ id: '1' })).not.toThrow()
    expect(mockGraph).not.toHaveProperty('refresh')
  })

  it('pins dragged node', () => {
    const p = props()
    render(<InteractiveGraph {...p} />)
    const node: { id: string; x: number; y: number; fx?: number; fy?: number } = { id: '1', x: 5, y: 6 }
    ;(mockCaptured.props.onNodeDragEnd as (draggedNode: typeof node) => void)(node)
    expect(p.onPinsChange).toHaveBeenCalledWith(new Set(['1']))
    expect(node.fx).toBe(5)
    expect(node.fy).toBe(6)
  })

  it('unpins cached dragged node when pinnedIds removes it', () => {
    const p = props()
    const { rerender } = render(<InteractiveGraph {...p} />)
    const node = (mockCaptured.props.graphData as { nodes: Array<{ id: string; x?: number; y?: number; fx?: number; fy?: number }> }).nodes[0]
    node.x = 5
    node.y = 6
    ;(mockCaptured.props.onNodeDragEnd as (draggedNode: typeof node) => void)(node)
    rerender(<InteractiveGraph {...p} pinnedIds={new Set(['1'])} />)
    mockGraph.d3ReheatSimulation.mockClear()

    rerender(<InteractiveGraph {...p} pinnedIds={new Set()} />)

    const cachedNode = (mockCaptured.props.graphData as { nodes: typeof node[] }).nodes[0]
    expect(cachedNode.fx).toBeNull()
    expect(cachedNode.fy).toBeNull()
    expect(mockGraph.d3ReheatSimulation).toHaveBeenCalled()
  })

  it('does not reheat when pinnedIds gains no stale pinned node', () => {
    const p = props()
    const { rerender } = render(<InteractiveGraph {...p} />)
    const node = (mockCaptured.props.graphData as { nodes: Array<{ id: string; x?: number; y?: number }> }).nodes[0]
    node.x = 5
    node.y = 6
    ;(mockCaptured.props.onNodeDragEnd as (draggedNode: typeof node) => void)(node)
    rerender(<InteractiveGraph {...p} pinnedIds={new Set(['1'])} />)
    mockGraph.d3ReheatSimulation.mockClear()

    rerender(<InteractiveGraph {...p} pinnedIds={new Set(['1', '2'])} />)
    expect(mockGraph.d3ReheatSimulation).not.toHaveBeenCalled()

    rerender(<InteractiveGraph {...p} pinnedIds={new Set(['2', '1'])} />)
    expect(mockGraph.d3ReheatSimulation).not.toHaveBeenCalled()
  })

  it('paints hub label while culling low-degree label when zoomed out', () => {
    render(<InteractiveGraph {...props()} />)
    const paint = mockCaptured.props.nodeCanvasObject as (
      node: GraphNode,
      ctx: CanvasRenderingContext2D,
      scale: number,
    ) => void
    const ctx = {
      fillStyle: '', fillRect() {}, beginPath() {}, arc() {}, fill() {}, stroke() {},
      measureText: () => ({ width: 10 }), fillText: vi.fn(), font: '', textAlign: '', textBaseline: '',
    } as unknown as CanvasRenderingContext2D
    paint(nodes[1], ctx, 0.5)
    expect(ctx.fillText).toHaveBeenCalledWith('hub', expect.any(Number), expect.any(Number))
    vi.mocked(ctx.fillText).mockClear()
    paint(nodes[0], ctx, 0.5)
    expect(ctx.fillText).not.toHaveBeenCalled()
  })

  it('multiplies current zoom through imperative handle', () => {
    const h = { current: null as GraphHandle | null }
    render(<InteractiveGraph {...props()} ref={h} />)
    h.current!.zoomBy(1.3)
    expect(mockGraph.zoom).toHaveBeenCalledWith(2.6, 400)
  })

  it('fits graph view from control', () => {
    render(<InteractiveGraph {...props()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Fit view' }))
    expect(mockGraph.zoomToFit).toHaveBeenCalledWith(400, 40)
  })

  it('handles 1,000 nodes and 2,000 edges', () => {
    const manyNodes = Array.from({ length: 1000 }, (_, i) => ({ id: `${i}`, slug: `${i}`, title: `${i}`, degree: 0 }))
    const manyEdges = Array.from({ length: 2000 }, (_, i) => ({ source: `${i % 1000}`, target: `${(i + 1) % 1000}`, score: 0.5, relation: 'related', origin: 'vector' }))
    render(<InteractiveGraph {...props()} nodes={manyNodes} edges={manyEdges} />)
    expect((mockCaptured.props.graphData as { nodes: GraphNode[] }).nodes).toHaveLength(1000)
  })

  it('keeps node objects stable across edge changes', () => {
    const p = props()
    const { rerender } = render(<InteractiveGraph {...p} />)
    const first = (mockCaptured.props.graphData as { nodes: GraphNode[] }).nodes
    rerender(<InteractiveGraph {...p} edges={[]} />)
    const second = (mockCaptured.props.graphData as { nodes: GraphNode[] }).nodes
    expect(second[0]).toBe(first[0])
    expect(second[1]).toBe(first[1])
  })
})
