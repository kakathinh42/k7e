interface FilterChipProps {
  label: string
  count?: number
  active: boolean
  onClick: () => void
}

/** A toggle-able facet filter chip (pill) with an optional count. */
export default function FilterChip({ label, count, active, onClick }: FilterChipProps) {
  return (
    <button
      type="button"
      className={`chip${active ? ' chip-active' : ''}`}
      aria-pressed={active}
      onClick={onClick}
    >
      {label}
      {count !== undefined && <span className="chip-count">{count}</span>}
    </button>
  )
}
