/**
 * Force-directed graph layout using d3-force.
 *
 * Obsidian-style tuning: strong centre gravity pulls the dense hub inward;
 * moderate repulsion keeps nodes legible; short link distance tightens
 * clusters. Deterministic: fixed circle seed → same layout every time.
 */
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceRadial,
} from 'd3-force'
import type { GraphEdge, GraphNode } from '../api'

export interface Point {
  x: number
  y: number
}
export type Positions = Record<string, Point>

export const LAYOUT_WIDTH = 960
export const LAYOUT_HEIGHT = 680

/** Node radius formula — must match GraphPage.tsx circle sizing. */
function nodeRadius(degree: number): number {
  return 3 + Math.min(degree, 12) * 0.58
}

export function computeLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  _iterations = 400,
): Positions {
  const n = nodes.length
  if (n === 0) return {}
  if (n === 1) {
    return { [nodes[0].id]: { x: LAYOUT_WIDTH / 2, y: LAYOUT_HEIGHT / 2 } }
  }

  // Seed nodes on a circle. Radius scales with count but stays bounded.
  const r = Math.min(Math.max(n * 8, 80), 240)
  type SimNode = { id: string; degree: number; x: number; y: number }
  const simNodes: SimNode[] = nodes.map((nd, i) => {
    const a = (2 * Math.PI * i) / n
    return {
      id: nd.id,
      degree: nd.degree,
      x: LAYOUT_WIDTH / 2 + Math.cos(a) * r,
      y: LAYOUT_HEIGHT / 2 + Math.sin(a) * r,
    }
  })

  const idxById = new Map(simNodes.map((nd, i) => [nd.id, i]))

  type SimLink = { source: number; target: number }
  const simLinks: SimLink[] = edges
    .map((e) => ({
      source: idxById.get(e.source) ?? -1,
      target: idxById.get(e.target) ?? -1,
    }))
    .filter((l) => l.source !== -1 && l.target !== -1)

  // Obsidian-style forces:
  //   - Strong centre gravity: pulls dense hubs to the middle
  //   - Moderate repulsion: keeps labels readable, not overly spread
  //   - Short link distance (50px): tightens clusters like Obsidian
  //   - Radial: isolated/low-degree nodes drift to outer ring
  //   - Collide: dots never overlap
  const sim = forceSimulation<SimNode>(simNodes)
    .force('center', forceCenter(LAYOUT_WIDTH / 2, LAYOUT_HEIGHT / 2).strength(1.0))
    .force('charge', forceManyBody<SimNode>().strength((nd) => -60 - nd.degree * 8))
    .force(
      'link',
      forceLink<SimNode, SimLink>(simLinks).distance(50).strength(0.9),
    )
    .force(
      'radial',
      forceRadial<SimNode>(
        // hub nodes (degree ≥ 4) pulled to inner ring; isolated nodes to outer
        (nd) => (nd.degree >= 4 ? 40 : 200),
        LAYOUT_WIDTH / 2,
        LAYOUT_HEIGHT / 2,
      ).strength((nd) => (nd.degree >= 4 ? 0.15 : 0.08)),
    )
    .force(
      'collide',
      forceCollide<SimNode>((nd) => nodeRadius(nd.degree) + 3),
    )
    .stop()

  // Run synchronous ticks — 400 is enough for 85 nodes to fully settle.
  const ticks = _iterations > 0 ? _iterations : 400
  for (let i = 0; i < ticks; i++) sim.tick()

  // Normalise into the viewBox with padding.
  const pad = 56
  const xs = simNodes.map((p) => p.x)
  const ys = simNodes.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const s = Math.min(
    (LAYOUT_WIDTH - 2 * pad) / Math.max(maxX - minX, 1),
    (LAYOUT_HEIGHT - 2 * pad) / Math.max(maxY - minY, 1),
  )
  const out: Positions = {}
  simNodes.forEach((nd) => {
    out[nd.id] = {
      x: Math.max(pad, Math.min(LAYOUT_WIDTH - pad, pad + (nd.x - minX) * s)),
      y: Math.max(pad, Math.min(LAYOUT_HEIGHT - pad, pad + (nd.y - minY) * s)),
    }
  })
  return out
}

/** Map each node id to a 0-based connected-component index. */
export function connectedComponents(
  nodes: GraphNode[],
  edges: GraphEdge[],
): Record<string, number> {
  const adj = new Map<string, string[]>()
  nodes.forEach((nd) => adj.set(nd.id, []))
  edges.forEach((e) => {
    adj.get(e.source)?.push(e.target)
    adj.get(e.target)?.push(e.source)
  })
  const comp: Record<string, number> = {}
  let c = 0
  for (const node of nodes) {
    if (node.id in comp) continue
    const stack = [node.id]
    comp[node.id] = c
    while (stack.length) {
      const cur = stack.pop() as string
      for (const nb of adj.get(cur) ?? []) {
        if (!(nb in comp)) {
          comp[nb] = c
          stack.push(nb)
        }
      }
    }
    c++
  }
  return comp
}

/** Undirected degree of each node for the given edge set. */
export function degreeMap(
  nodes: GraphNode[],
  edges: GraphEdge[],
): Record<string, number> {
  const deg: Record<string, number> = {}
  nodes.forEach((n) => (deg[n.id] = 0))
  edges.forEach((e) => {
    if (e.source in deg) deg[e.source] += 1
    if (e.target in deg) deg[e.target] += 1
  })
  return deg
}
