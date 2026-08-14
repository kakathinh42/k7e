import { describe, it, expect } from 'vitest'
import {
  computeLayout,
  connectedComponents,
  degreeMap,
  LAYOUT_HEIGHT,
  LAYOUT_WIDTH,
} from './graphLayout'
import type { GraphEdge, GraphNode } from '../api'

const node = (id: string): GraphNode => ({ id, slug: id, title: id, degree: 0 })
const edge = (s: string, t: string, score = 0.8, origin = 'vector'): GraphEdge => ({
  source: s,
  target: t,
  score,
  relation: 'related',
  origin,
})

describe('computeLayout', () => {
  it('returns empty for no nodes', () => {
    expect(computeLayout([], [])).toEqual({})
  })

  it('centres a single node', () => {
    const pos = computeLayout([node('a')], [])
    expect(pos.a).toEqual({ x: LAYOUT_WIDTH / 2, y: LAYOUT_HEIGHT / 2 })
  })

  it('keeps all nodes within the viewBox', () => {
    const nodes = ['a', 'b', 'c', 'd'].map(node)
    const pos = computeLayout(nodes, [edge('a', 'b'), edge('c', 'd')])
    for (const id of ['a', 'b', 'c', 'd']) {
      expect(pos[id].x).toBeGreaterThanOrEqual(0)
      expect(pos[id].x).toBeLessThanOrEqual(LAYOUT_WIDTH)
      expect(pos[id].y).toBeGreaterThanOrEqual(0)
      expect(pos[id].y).toBeLessThanOrEqual(LAYOUT_HEIGHT)
    }
  })

  it('is deterministic for the same input', () => {
    const nodes = ['a', 'b', 'c'].map(node)
    const edges = [edge('a', 'b'), edge('b', 'c')]
    expect(computeLayout(nodes, edges)).toEqual(computeLayout(nodes, edges))
  })
})

describe('connectedComponents', () => {
  it('groups linked nodes and separates unlinked ones', () => {
    const nodes = ['a', 'b', 'c'].map(node)
    const comp = connectedComponents(nodes, [edge('a', 'b')])
    expect(comp.a).toBe(comp.b)
    expect(comp.c).not.toBe(comp.a)
    expect(new Set(Object.values(comp)).size).toBe(2)
  })
})

describe('degreeMap', () => {
  it('counts undirected degree from the edge set', () => {
    const nodes = ['a', 'b', 'c'].map(node)
    const deg = degreeMap(nodes, [edge('a', 'b'), edge('a', 'c')])
    expect(deg).toEqual({ a: 2, b: 1, c: 1 })
  })
})
