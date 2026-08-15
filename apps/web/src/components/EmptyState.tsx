import type { ReactNode } from 'react'

export default function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>
}
