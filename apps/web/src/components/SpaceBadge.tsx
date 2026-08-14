import type { SpaceRef } from '../api'

interface KindMeta {
  icon: string
  className: string
  kindLabel: string
  hint: string
}

/** The single styling + labelling source for a space's kind. */
export const SPACE_KIND_META: Record<string, KindMeta> = {
  personal: {
    icon: '🔒',
    className: 'badge-space-personal',
    kindLabel: 'Private',
    hint: 'Your private space — only you can see it',
  },
  team: {
    icon: '👥',
    className: 'badge-space-team',
    kindLabel: 'Team',
    hint: 'A team space — shared with the team',
  },
  public: {
    icon: '🌐',
    className: 'badge-space-public',
    kindLabel: 'Public',
    hint: 'Shared across your org',
  },
}

interface Props {
  space?: SpaceRef | null
  /** Show the space name (default) or just the kind label. */
  showName?: boolean
}

/** A pill showing which space a page lives in: 🔒 Private · 👥 Team · 🌐 Public. */
export default function SpaceBadge({ space, showName = true }: Props) {
  if (!space) return null
  const meta = SPACE_KIND_META[space.kind] ?? SPACE_KIND_META.public
  return (
    <span
      className={`badge badge-space ${meta.className}`}
      title={`${meta.kindLabel} — ${meta.hint}`}
    >
      <span aria-hidden="true">{meta.icon}</span>
      {showName ? space.name : meta.kindLabel}
    </span>
  )
}
