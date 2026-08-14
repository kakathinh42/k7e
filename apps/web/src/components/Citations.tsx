function asRecord(c: unknown): Record<string, unknown> {
  return c && typeof c === 'object' ? (c as Record<string, unknown>) : {}
}
function pickString(rec: Record<string, unknown>, keys: string[]): string | undefined {
  for (const k of keys) {
    const v = rec[k]
    if (typeof v === 'string' && v.trim()) return v
  }
  return undefined
}

export default function Citations({ citations }: { citations: unknown[] }) {
  if (!citations || citations.length === 0) {
    return <p className="meta">No citations.</p>
  }
  return (
    <ul className="stack" style={{ listStyle: 'none', paddingLeft: 0 }}>
      {citations.map((c, i) => {
        const rec = asRecord(c)
        const url = pickString(rec, ['url', 'source_url', 'link'])
        const title = pickString(rec, ['title', 'source', 'name']) ?? url ?? `Citation ${i + 1}`
        const snippet = pickString(rec, ['snippet', 'quote', 'text'])
        return (
          <li className="card" key={i}>
            {url ? (
              <a href={url} target="_blank" rel="noreferrer">
                {title}
              </a>
            ) : (
              <strong>{title}</strong>
            )}
            {snippet && <p className="meta" style={{ marginTop: 'var(--space-2)' }}>{snippet}</p>}
          </li>
        )
      })}
    </ul>
  )
}
