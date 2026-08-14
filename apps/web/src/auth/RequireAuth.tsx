/**
 * auth/RequireAuth.tsx — route guard for the protected app shell.
 * dev mode passes through. password mode redirects to /login (with the
 * attempted path preserved as ?returnTo=) when unauthenticated.
 */

import { type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import Skeleton from '../components/Skeleton'
import { useAuth } from './AuthContext'

export default function RequireAuth({ children }: { children: ReactNode }) {
  const { mode, status } = useAuth()
  const location = useLocation()
  const returnTo = location.pathname + location.search

  if (mode === 'dev' || status === 'authenticated') return <>{children}</>
  if (status === 'loading') {
    return (
      <div className="content">
        <Skeleton width="40%" />
      </div>
    )
  }
  return <Navigate to={`/login?returnTo=${encodeURIComponent(returnTo)}`} replace />
}
