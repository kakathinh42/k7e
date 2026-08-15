import { Link } from 'react-router-dom'
import type { SourceRef } from '../api'

/**
 * Renders a page's verifiable provenance:
 *  - "Compiled from" — the originating raw document(s) of a source page.
 *  - "Derived from" — the source page(s) a derived page was compiled from.
 * Renders nothing when there is no provenance.
 */
export default function Sources({ sources }: { sources: SourceRef[] }) {
  if (!sources || sources.length === 0) {
    return null
  }
  const documents = sources.filter((s) => s.kind === 'document')
  const pages = sources.filter((s) => s.kind === 'page')

  return (
    <div className="stack">
      {documents.length > 0 && (
        <div className="stack">
          <p className="meta">Compiled from</p>
          <ul className="stack" style={{ listStyle: 'none', paddingLeft: 0 }}>
            {documents.map((d, i) => (
              <li className="card" key={d.raw_document_id ?? i}>
                <strong>📄 {d.label}</strong>
                {d.source_system && (
                  <p className="meta" style={{ marginTop: 'var(--space-2)' }}>
                    {d.source_system}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {pages.length > 0 && (
        <div className="stack">
          <p className="meta">Derived from</p>
          <ul className="stack" style={{ listStyle: 'none', paddingLeft: 0 }}>
            {pages.map((p, i) => (
              <li className="card" key={p.slug ?? i}>
                <Link to={`/items/${p.slug}`}>{p.title}</Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
