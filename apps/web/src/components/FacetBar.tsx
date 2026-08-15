import { useState } from 'react'
import FilterChip from './FilterChip'
import Button from './Button'
import type { Facets } from '../api'

/** Tags are long-tailed; show the most common ones and collapse the rest. */
const TAG_LIMIT = 12

interface FacetBarProps {
  facets?: Facets
  selected: { domain?: string; tags: string[]; type?: string }
  showType: boolean
  onToggleDomain: (value: string) => void
  onToggleTag: (value: string) => void
  onToggleType: (value: string) => void
  onClear: () => void
}

/** Presentational facet chip bar: domain (single), tags (multi), type (single). */
export default function FacetBar({
  facets,
  selected,
  showType,
  onToggleDomain,
  onToggleTag,
  onToggleType,
  onClear,
}: FacetBarProps) {
  const [tagsExpanded, setTagsExpanded] = useState(false)
  if (!facets) return null

  const hasFilter =
    Boolean(selected.domain) || selected.tags.length > 0 || Boolean(selected.type)
  const empty =
    facets.domains.length === 0 && facets.tags.length === 0 && facets.types.length === 0
  if (empty && !hasFilter) return null

  // Collapsed view: the top TAG_LIMIT by count, plus any selected tag that would
  // otherwise fall below the fold (so active filters always stay visible).
  const hasMoreTags = facets.tags.length > TAG_LIMIT
  const topTags = facets.tags.slice(0, TAG_LIMIT)
  const collapsedTags = [
    ...topTags,
    ...facets.tags.filter(
      (t) => selected.tags.includes(t.value) && !topTags.some((x) => x.value === t.value),
    ),
  ]
  const visibleTags = tagsExpanded ? facets.tags : collapsedTags

  return (
    <div className="facet-bar" role="group" aria-label="Filters">
      {facets.domains.length > 0 && (
        <div className="facet-group">
          <span className="facet-group-label">domain</span>
          {facets.domains.map((d) => (
            <FilterChip
              key={d.value}
              label={d.value}
              count={d.count}
              active={selected.domain === d.value}
              onClick={() => onToggleDomain(d.value)}
            />
          ))}
        </div>
      )}
      {facets.tags.length > 0 && (
        <div className="facet-group">
          <span className="facet-group-label">tags</span>
          {visibleTags.map((t) => (
            <FilterChip
              key={t.value}
              label={t.value}
              count={t.count}
              active={selected.tags.includes(t.value)}
              onClick={() => onToggleTag(t.value)}
            />
          ))}
          {hasMoreTags && (
            <button
              type="button"
              className="chip chip-more"
              aria-expanded={tagsExpanded}
              onClick={() => setTagsExpanded((v) => !v)}
            >
              {tagsExpanded ? 'show less' : `+${facets.tags.length - visibleTags.length} more`}
            </button>
          )}
        </div>
      )}
      {showType && facets.types.length > 0 && (
        <div className="facet-group">
          <span className="facet-group-label">type</span>
          {facets.types.map((t) => (
            <FilterChip
              key={t.value}
              label={t.value}
              count={t.count}
              active={selected.type === t.value}
              onClick={() => onToggleType(t.value)}
            />
          ))}
        </div>
      )}
      {hasFilter && (
        <div className="facet-group">
          <Button variant="ghost" onClick={onClear}>
            Clear filters
          </Button>
        </div>
      )}
    </div>
  )
}
