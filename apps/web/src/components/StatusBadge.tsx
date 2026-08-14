interface StatusMeta { className: string; label: string }

const MAP: Record<string, StatusMeta> = {
  published: { className: 'badge-published', label: 'Published' },
  publish: { className: 'badge-published', label: 'Publish' },
  review: { className: 'badge-review', label: 'In review' },
  pending: { className: 'badge-review', label: 'Pending' },
  rejected: { className: 'badge-rejected', label: 'Rejected' },
  reject: { className: 'badge-rejected', label: 'Reject' },
  draft: { className: 'badge-draft', label: 'Draft' },
}

function fallback(status: string): StatusMeta {
  const label = status ? status[0].toUpperCase() + status.slice(1) : 'Unknown'
  return { className: 'badge-draft', label }
}

export default function StatusBadge({ status }: { status: string }) {
  const meta = MAP[status?.toLowerCase()] ?? fallback(status)
  return <span className={`badge ${meta.className}`}>{meta.label}</span>
}
