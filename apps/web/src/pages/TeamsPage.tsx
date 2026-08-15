import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { listTeams, createTeam, type Team } from '../api'
import Button from '../components/Button'
import Card from '../components/Card'
import Alert from '../components/Alert'
import EmptyState from '../components/EmptyState'
import Skeleton from '../components/Skeleton'

export default function TeamsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [slug, setSlug] = useState('')
  const [name, setName] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const { data: teams, isLoading, error } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: listTeams,
  })

  async function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const s = slug.trim()
    const n = name.trim()
    if (!s || !n) {
      setCreateError('Slug and name are required.')
      return
    }
    setCreating(true)
    setCreateError(null)
    try {
      const team = await createTeam(s, n)
      await qc.invalidateQueries({ queryKey: ['teams'] })
      navigate(`/teams/${team.slug}`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      setCreateError(
        msg.startsWith('HTTP 409')
          ? 'That slug is already taken.'
          : msg || 'Failed to create team.',
      )
    } finally {
      setCreating(false)
    }
  }

  return (
    <main className="stack">
      <h1>Teams</h1>

      <Card>
        <form onSubmit={handleCreate} className="stack">
          <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <input
              className="input"
              aria-label="Team slug"
              placeholder="slug (e.g. platform)"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
            />
            <input
              className="input"
              aria-label="Team name"
              placeholder="Name (e.g. Platform Team)"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Button type="submit" variant="primary" disabled={creating}>
              {creating ? 'Creating…' : 'Create team'}
            </Button>
          </div>
        </form>
      </Card>

      {createError && <Alert>{createError}</Alert>}

      {isLoading && (
        <>
          <div className="card"><Skeleton width="50%" /></div>
          <div className="card"><Skeleton width="40%" /></div>
        </>
      )}
      {error && (
        <Alert>Error loading teams: {error instanceof Error ? error.message : 'Unknown error'}</Alert>
      )}
      {teams && teams.length === 0 && <EmptyState>No teams yet — create one above.</EmptyState>}
      {teams && teams.length > 0 && (
        <section className="stack">
          {teams.map((team) => (
            <Link className="card card-link" to={`/teams/${team.slug}`} key={team.id}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                <strong>{team.name}</strong>
                <span className="meta" style={{ marginLeft: 'auto' }}>
                  {team.members.length} member{team.members.length === 1 ? '' : 's'}
                </span>
              </div>
            </Link>
          ))}
        </section>
      )}
    </main>
  )
}
