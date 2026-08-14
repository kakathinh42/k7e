import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getTeam,
  addMember,
  removeMember,
  type Team,
} from '../api'
import { useAuth } from '../auth/AuthContext'
import Button from '../components/Button'
import Card from '../components/Card'
import Alert from '../components/Alert'
import Skeleton from '../components/Skeleton'

const ADDABLE_ROLES = ['member', 'admin', 'viewer'] as const

export default function TeamDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const { user } = useAuth()
  const currentUserId = user?.id ?? ''
  const qc = useQueryClient()
  const [newUser, setNewUser] = useState('')
  const [newRole, setNewRole] = useState('member')
  const [mutError, setMutError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const { data: team, isLoading, error } = useQuery<Team>({
    queryKey: ['team', slug],
    queryFn: () => getTeam(slug!),
    enabled: Boolean(slug),
    retry: (failureCount, err) =>
      err instanceof Error && err.message.startsWith('HTTP 404') ? false : failureCount < 2,
  })

  const canAdmin =
    team?.members.some(
      (m) => m.user_id === currentUserId && (m.role === 'owner' || m.role === 'admin'),
    ) ?? false

  async function handleAdd(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!slug) return
    const uid = newUser.trim()
    if (!uid) {
      setMutError('User ID is required.')
      return
    }
    setMutError(null)
    setBusy(true)
    try {
      await addMember(slug, uid, newRole)
      setNewUser('')
      setNewRole('member')
      await qc.invalidateQueries({ queryKey: ['team', slug] })
    } catch (err) {
      setMutError(err instanceof Error ? err.message : 'Failed to add member.')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemove(userId: string) {
    if (!slug) return
    setMutError(null)
    setBusy(true)
    try {
      await removeMember(slug, userId)
      await qc.invalidateQueries({ queryKey: ['team', slug] })
    } catch (err) {
      setMutError(err instanceof Error ? err.message : 'Failed to remove member.')
    } finally {
      setBusy(false)
    }
  }

  if (!slug) {
    return (
      <main><h1>Team Not Found</h1><p className="meta">No slug provided.</p></main>
    )
  }
  if (isLoading) {
    return (
      <main className="stack">
        <Skeleton width="40%" />
        <div className="card"><Skeleton width="70%" /></div>
      </main>
    )
  }
  if (error || !team) {
    const is404 = error instanceof Error && error.message.startsWith('HTTP 404')
    const showNotFound = is404 || !error
    return (
      <main className="stack">
        <h1>{showNotFound ? 'Team Not Found' : 'Error'}</h1>
        <Alert>
          {showNotFound
            ? 'Team not found, or you are not a member.'
            : error instanceof Error
              ? error.message
              : 'Unknown error'}
        </Alert>
        <p><Link to="/teams">← Back to teams</Link></p>
      </main>
    )
  }

  return (
    <main className="stack">
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <h1>{team.name}</h1>
        <span className="meta">{team.slug}</span>
      </div>

      {mutError && <Alert>{mutError}</Alert>}

      <Card>
        <table className="data-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Joined</th>
              {canAdmin && <th />}
            </tr>
          </thead>
          <tbody>
            {team.members.map((m) => (
              <tr key={m.user_id}>
                <td>{m.user_id}</td>
                <td>{m.role}</td>
                <td className="meta">{new Date(m.created_at).toLocaleDateString()}</td>
                {canAdmin && (
                  <td>
                    {m.user_id !== currentUserId && (
                      <Button
                        variant="ghost"
                        aria-label={`Remove ${m.user_id}`}
                        disabled={busy}
                        onClick={() => handleRemove(m.user_id)}
                      >
                        Remove
                      </Button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {canAdmin && (
        <Card>
          <form
            onSubmit={handleAdd}
            style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}
          >
            <input
              className="input"
              aria-label="New member user id"
              placeholder="user_id"
              value={newUser}
              onChange={(e) => setNewUser(e.target.value)}
            />
            <select
              className="input"
              aria-label="New member role"
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
            >
              {ADDABLE_ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <Button type="submit" variant="primary" disabled={busy}>Add member</Button>
          </form>
        </Card>
      )}
    </main>
  )
}
