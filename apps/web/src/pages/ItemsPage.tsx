import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listItems, listSpaces, search, getFacets, type ItemSummary, type SearchResponse, type Facets, type Space } from '../api'
import FacetBar from '../components/FacetBar'
import FilterChip from '../components/FilterChip'
import StatusBadge from '../components/StatusBadge'
import SpaceBadge, { SPACE_KIND_META } from '../components/SpaceBadge'
import Skeleton from '../components/Skeleton'
import EmptyState from '../components/EmptyState'
import Alert from '../components/Alert'
import Button from '../components/Button'

/** Leading glyph per OKF page type, for the tab row + item rows. */
const TYPE_META: Record<string, string> = {
  source: '📄',
  concept: '💡',
  entity: '🏷',
  analysis: '📊',
}

/**
 * The Browse type tabs. Sources (the raw "main" page per ingest) is the
 * default view; `all` is a sentinel that drops the type filter so every type
 * — including `analysis` — shows. Fixed, not facet-derived, so the tabs are
 * stable and independent of the current space.
 */
const TYPE_TABS: { key: string; label: string }[] = [
  { key: 'source', label: `${TYPE_META.source} Sources` },
  { key: 'concept', label: `${TYPE_META.concept} Concepts` },
  { key: 'entity', label: `${TYPE_META.entity} Entities` },
  { key: 'all', label: 'All' },
]

export default function ItemsPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const domain = params.get('domain') ?? undefined
  const typeParam = params.get('type') ?? undefined
  const tags = params.getAll('tag')
  const space = params.get('space') ?? undefined
  const searching = q.length > 0

  // The Sources tab is the default (no ?type=). `all` is a sentinel meaning
  // "no type filter"; any other value pins that exact type.
  const activeType = typeParam ?? 'source'
  const typeFilter = activeType === 'all' ? undefined : activeType

  const [queryInput, setQueryInput] = useState(q)
  const [explain, setExplain] = useState(false)

  const { data: facets } = useQuery<Facets>({ queryKey: ['facets'], queryFn: getFacets })
  const { data: spaces } = useQuery<Space[]>({ queryKey: ['spaces'], queryFn: () => listSpaces() })

  const browseQuery = useQuery<ItemSummary[]>({
    queryKey: ['items', { domain, tags, type: typeFilter, space }],
    queryFn: () => listItems({ domain, tags, type: typeFilter, space }),
    enabled: !searching,
  })
  const searchQuery = useQuery<SearchResponse>({
    queryKey: ['search', q, { domain, tags, explain, space }],
    queryFn: () => search(q, { domain, tags, explain, space }),
    enabled: searching,
  })

  const isLoading = searching ? searchQuery.isLoading : browseQuery.isLoading
  const error = searching ? searchQuery.error : browseQuery.error

  // The URL is the single source of truth; every mutation rewrites it.
  function mutateParams(mutate: (p: URLSearchParams) => void) {
    const next = new URLSearchParams(params)
    mutate(next)
    setParams(next)
  }
  const toggleDomain = (v: string) =>
    mutateParams((p) => (p.get('domain') === v ? p.delete('domain') : p.set('domain', v)))
  const toggleType = (v: string) =>
    mutateParams((p) => (p.get('type') === v ? p.delete('type') : p.set('type', v)))
  // Tab select: Sources is the default, so it clears ?type= for a clean URL;
  // every other tab pins its value (with `all` as the show-everything sentinel).
  const setType = (key: string) =>
    mutateParams((p) => (key === 'source' ? p.delete('type') : p.set('type', key)))
  const toggleTag = (v: string) =>
    mutateParams((p) => {
      const current = p.getAll('tag')
      p.delete('tag')
      const nextTags = current.includes(v) ? current.filter((t) => t !== v) : [...current, v]
      nextTags.forEach((t) => p.append('tag', t))
    })
  const clearFilters = () =>
    mutateParams((p) => {
      p.delete('domain')
      p.delete('type')
      p.delete('tag')
    })
  const setSpace = (slug: string | undefined) =>
    mutateParams((p) => (slug ? p.set('space', slug) : p.delete('space')))
  function onSearchSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    mutateParams((p) => {
      const s = queryInput.trim()
      if (s) p.set('q', s)
      else p.delete('q')
    })
  }

  const items = browseQuery.data
  const hits = searchQuery.data?.hits

  return (
    <main className="stack">
      <h1>Browse</h1>

      <form onSubmit={onSearchSubmit} style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <label htmlFor="search-input" className="meta" style={{ alignSelf: 'center' }}>Search</label>
        <input
          id="search-input"
          className="input"
          style={{ flex: 1 }}
          type="text"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder="Enter search query…"
        />
        <Button type="submit" variant="primary">Search</Button>
      </form>

      {spaces && spaces.length > 1 && (
        <div className="space-tabs" role="tablist" aria-label="Filter by space">
          <FilterChip label="All" active={!space} onClick={() => setSpace(undefined)} />
          {spaces.map((s) => (
            <FilterChip
              key={s.slug}
              label={`${SPACE_KIND_META[s.kind]?.icon ?? ''} ${s.name}`}
              count={s.item_count}
              active={space === s.slug}
              onClick={() => setSpace(s.slug)}
            />
          ))}
        </div>
      )}

      {!searching && (
        <div className="type-tabs" role="tablist" aria-label="Filter by page type">
          {TYPE_TABS.map((t) => (
            <FilterChip
              key={t.key}
              label={t.label}
              active={activeType === t.key}
              onClick={() => setType(t.key)}
            />
          ))}
        </div>
      )}

      <FacetBar
        facets={facets}
        selected={{ domain, tags }}
        showType={false}
        onToggleDomain={toggleDomain}
        onToggleTag={toggleTag}
        onToggleType={toggleType}
        onClear={clearFilters}
      />

      {q && (
        <label className="explain-toggle">
          <input
            type="checkbox"
            checked={explain}
            onChange={(e) => setExplain(e.target.checked)}
          />
          Explain scores
        </label>
      )}

      {error && <Alert>Error: {error instanceof Error ? error.message : 'Unknown error'}</Alert>}
      {isLoading && (
        <>
          <div className="card"><Skeleton width="60%" /></div>
          <div className="card"><Skeleton width="45%" /></div>
        </>
      )}

      {searching
        ? hits &&
          (hits.length === 0 ? (
            <EmptyState>No results match these filters.</EmptyState>
          ) : (
            hits.map((hit) => (
              <div key={hit.id}>
                <Link className="card card-link" to={`/items/${hit.slug}`}>
                  <strong>{hit.title}</strong>
                  {hit.snippet && (
                    <p className="meta" style={{ marginTop: 'var(--space-2)' }}>{hit.snippet}</p>
                  )}
                </Link>
                {hit.breakdown && (
                  <div className="score-breakdown" data-testid="score-breakdown">
                    <span className="score-total">
                      total <b>{hit.breakdown.total.toFixed(3)}</b>
                    </span>
                    {hit.breakdown.expanded ? (
                      <span className="score-part">
                        ↳ via <b>{hit.breakdown.via}</b> (edge{' '}
                        {hit.breakdown.edge_score?.toFixed(2)})
                      </span>
                    ) : (
                      // Raw 0–1 signals; the weight (shown on hover) is applied to
                      // the score, not the displayed value. Only signals with a
                      // non-zero weight are shown, so the panel mirrors the live
                      // formula (recency + importance are disabled by default).
                      (['keyword', 'vector', 'recency', 'importance'] as const)
                        .filter((sig) => (hit.breakdown!.weights?.[sig] ?? 0) > 0)
                        .map((sig) => {
                        const bd = hit.breakdown!
                        const raw = bd[sig] ?? 0
                        const weight = bd.weights?.[sig] ?? 1
                        return (
                          <span
                            className="score-part"
                            key={sig}
                            title={`raw ${raw.toFixed(3)} × weight ${weight} = ${(
                              weight * raw
                            ).toFixed(3)}`}
                          >
                            {sig} {raw.toFixed(2)}
                            <span className="score-max">/1</span>
                          </span>
                        )
                      })
                    )}
                  </div>
                )}
              </div>
            ))
          ))
        : items &&
          (items.length === 0 ? (
            <EmptyState>No items match these filters.</EmptyState>
          ) : (
            items.map((item) => (
              <Link className="card card-link" to={`/items/${item.slug}`} key={item.id}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                  <span className="type-icon" title={item.type} aria-hidden>
                    {TYPE_META[item.type] ?? TYPE_META.source}
                  </span>
                  <strong>{item.title}</strong>
                  <SpaceBadge space={item.space} />
                  <StatusBadge status={item.status} />
                  {item.domain && <span className="badge badge-neutral">{item.domain}</span>}
                  {item.tags.map((t) => (
                    <span className="badge badge-neutral" key={t}>{t}</span>
                  ))}
                  <span className="meta" style={{ marginLeft: 'auto' }}>
                    {new Date(item.updated_at).toLocaleDateString()}
                  </span>
                </div>
              </Link>
            ))
          ))}
    </main>
  )
}
