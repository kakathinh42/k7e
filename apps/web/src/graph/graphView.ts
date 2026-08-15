/** Pure graph view helpers — single source of node sizing/labels/adjacency. */
import type { GraphEdge, GraphNode } from '../api'

/** Obsidian-style node radius: min 3 px, max at degree 12. */
export function nodeRadius(degree: number): number {
  return 3 + Math.min(degree, 12) * 0.58
}

/** Hub colour threshold. */
export function isHub(degree: number): boolean {
  return degree >= 5
}

/** Undirected degree of each node for the given edge set. */
export function degreeMap(nodes: GraphNode[], edges: GraphEdge[]): Record<string, number> {
  const deg: Record<string, number> = {}
  nodes.forEach((n) => (deg[n.id] = 0))
  edges.forEach((e) => {
    if (e.source in deg) deg[e.source] += 1
    if (e.target in deg) deg[e.target] += 1
  })
  return deg
}

/** Map each node id to a 0-based connected-component index. */
export function connectedComponents(
  nodes: GraphNode[],
  edges: GraphEdge[],
): Record<string, number> {
  const adj = neighborSets(nodes, edges)
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

/** Adjacency sets (undirected) for hover highlighting. */
export function neighborSets(
  nodes: GraphNode[],
  edges: GraphEdge[],
): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>()
  nodes.forEach((n) => adj.set(n.id, new Set()))
  edges.forEach((e) => {
    adj.get(e.source)?.add(e.target)
    adj.get(e.target)?.add(e.source)
  })
  return adj
}

/** Label culling: priority nodes always, hubs when zoomed out, all when close. */
export function labelVisible(degree: number, isPriority: boolean, globalScale: number): boolean {
  return isPriority || degree >= 5 || globalScale >= 1.5
}
