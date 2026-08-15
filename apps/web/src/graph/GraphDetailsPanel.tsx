import type { GraphNode } from '../api'
import { isHub } from './graphView'

export interface GraphDetailsPanelProps {
  node: GraphNode | null
  neighbors: Array<{ node: GraphNode; origin: string; score: number }>
  pinned: boolean
  onSelect: (id: string) => void
  onOpen: (slug: string) => void
  onUnpin: () => void
  onClose: () => void
}

export default function GraphDetailsPanel({
  node, neighbors, pinned, onSelect, onOpen, onUnpin, onClose,
}: GraphDetailsPanelProps) {
  if (!node) return null

  return (
    <aside aria-label="Node details" style={{ width: 280, flexShrink: 0 }}>
      <header>
        <h2>{node.title}</h2>
        <button aria-label="Close details" onClick={onClose}>×</button>
      </header>
      <dl>
        <dt>Slug</dt><dd>{node.slug}</dd>
        <dt>Degree</dt><dd>{node.degree}</dd>
      </dl>
      {isHub(node.degree) && <span>Hub</span>}
      {pinned && <button onClick={onUnpin}>Unpin</button>}
      <ul>
        {neighbors.map(({ node: neighbor, origin }) => (
          <li key={neighbor.id}>
            <button onClick={() => onSelect(neighbor.id)}>
              {neighbor.title} <span title={origin}>●</span>
            </button>
          </li>
        ))}
      </ul>
      <button onClick={() => onOpen(node.slug)}>Open item</button>
    </aside>
  )
}
