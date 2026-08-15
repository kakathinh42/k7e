import { describe, it, expect } from 'vitest'
import {
  nodeRadius,
  isHub,
  degreeMap,
  connectedComponents,
  neighborSets,
  labelVisible,
} from './graphView'
import type { GraphEdge, GraphNode } from '../api'

const n = (id: string, degree = 0): GraphNode => ({ id, slug: id, title: id, degree })
const e = (source: string, target: string): GraphEdge =>
  ({ source, target, score: 0.5, relation: 'related', origin: 'vector' })

describe('nodeRadius', () => {
  it('min 3px at degree 0, capped at degree 12', () => {
    expect(nodeRadius(0)).toBe(3)
    expect(nodeRadius(12)).toBe(3 + 12 * 0.58)
    expect(nodeRadius(50)).toBe(3 + 12 * 0.58)
  })
})

describe('isHub', () => {
  it('true at degree >= 5', () => {
    expect(isHub(4)).toBe(false)
    expect(isHub(5)).toBe(true)
  })
})

describe('degreeMap', () => {
  it('counts undirected degree', () => {
    const d = degreeMap([n('a'), n('b'), n('c')], [e('a', 'b'), e('b', 'c'), e('c', 'b')])
    expect(d).toEqual({ a: 1, b: 3, c: 2 })
  })
})

describe('connectedComponents', () => {
  it('labels isolated nodes as own component', () => {
    const c = connectedComponents([n('a'), n('b'), n('z')], [e('a', 'b')])
    expect(c.a).toBe(c.b)
    expect(c.z).not.toBe(c.a)
  })
})

describe('neighborSets', () => {
  it('maps each node to its direct neighbors', () => {
    const m = neighborSets([n('a'), n('b'), n('c')], [e('a', 'b'), e('b', 'c')])
    expect(m.get('a')).toEqual(new Set(['b']))
    expect(m.get('b')).toEqual(new Set(['a', 'c']))
    expect(m.get('c')).toEqual(new Set(['b']))
  })
})

describe('labelVisible', () => {
  it('priority (hovered/selected) always visible', () => {
    expect(labelVisible(0, true, 0.5)).toBe(true)
  })
  it('hubs visible when zoomed out', () => {
    expect(labelVisible(5, false, 0.5)).toBe(true)
    expect(labelVisible(4, false, 0.5)).toBe(false)
  })
  it('all labels at globalScale >= 1.5', () => {
    expect(labelVisible(0, false, 1.5)).toBe(true)
  })
})
