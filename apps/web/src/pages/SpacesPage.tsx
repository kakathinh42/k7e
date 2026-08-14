import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listSpaces, type Space } from '../api'
import { SPACE_KIND_META } from '../components/SpaceBadge'

export default function SpacesPage() {
  const spaces = useQuery<Space[]>({ queryKey: ['spaces'], queryFn: () => listSpaces() })

  return (
    <main className="stack">
      <h1>Spaces</h1>
      <p className="meta">
        Where your knowledge lives — 🔒 private notes, 👥 team spaces, and the 🌐
        shared org corpus. Click a space to browse its pages.
      </p>
      {spaces.isLoading && <p className="meta">Loading…</p>}
      {spaces.data && spaces.data.length === 0 && <p className="meta">No spaces yet.</p>}
      <div className="dashboard-grid">
        {spaces.data?.map((s) => {
          const meta = SPACE_KIND_META[s.kind] ?? SPACE_KIND_META.public
          return (
            <Link
              key={s.slug}
              to={`/items?space=${encodeURIComponent(s.slug)}`}
              className="card card-link"
            >
              <div className="stat-value" style={{ fontSize: '1.4rem' }}>
                <span aria-hidden="true">{meta.icon}</span> {s.name}
              </div>
              <div className="stat-label">
                {meta.kindLabel} · {s.item_count} page{s.item_count === 1 ? '' : 's'}
              </div>
            </Link>
          )
        })}
      </div>
    </main>
  )
}
