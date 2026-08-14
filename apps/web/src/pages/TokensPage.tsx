/**
 * TokensPage — manage Personal Access Tokens. Generate a token (its plaintext
 * is shown ONCE, with a copy button), list existing tokens (never the
 * plaintext), and revoke. Paste a token into chat-agent to search + save to the
 * wiki as yourself.
 */

import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createPat,
  listPats,
  revokePat,
  type Pat,
  type PatCreated,
} from '../api'
import Alert from '../components/Alert'
import Button from '../components/Button'
import Card from '../components/Card'

export default function TokensPage() {
  const qc = useQueryClient()
  const pats = useQuery<Pat[]>({ queryKey: ['pats'], queryFn: () => listPats() })
  const [name, setName] = useState('')
  const [created, setCreated] = useState<PatCreated | null>(null)
  const [error, setError] = useState<string | null>(null)

  const createMut = useMutation({
    mutationFn: (n: string) => createPat(n),
    onSuccess: (res) => {
      setCreated(res)
      setName('')
      void qc.invalidateQueries({ queryKey: ['pats'] })
    },
    onError: () => setError('Could not create the token. Please try again.'),
  })

  const revokeMut = useMutation({
    mutationFn: (id: string) => revokePat(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['pats'] }),
  })

  function onGenerate(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (name.trim()) createMut.mutate(name.trim())
  }

  return (
    <main className="stack">
      <h1>Personal Access Tokens</h1>
      <p className="meta">
        Generate a token and paste it into chat-agent — it will search and save
        to the wiki as you. Treat it like a password; you can revoke it anytime.
      </p>

      <Card>
        <form className="form-stack" onSubmit={onGenerate}>
          <div className="field">
            <label className="meta" htmlFor="pat-name">
              Token name
            </label>
            <input
              id="pat-name"
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. laptop"
              required
            />
          </div>
          <Button type="submit" variant="primary" disabled={createMut.isPending}>
            {createMut.isPending ? 'Generating…' : 'Generate token'}
          </Button>
        </form>
      </Card>

      {error && <Alert>{error}</Alert>}

      {created && (
        <Card>
          <div className="stack">
            <strong>Copy your token now — it won&apos;t be shown again.</strong>
            <code className="input" style={{ wordBreak: 'break-all' }}>
              {created.token}
            </code>
            <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
              <Button
                variant="primary"
                onClick={() => void navigator.clipboard?.writeText(created.token)}
              >
                Copy
              </Button>
              <Button variant="ghost" onClick={() => setCreated(null)}>
                Done
              </Button>
            </div>
          </div>
        </Card>
      )}

      <Card>
        <h2 className="meta">Your tokens</h2>
        {pats.isLoading && <p className="meta">Loading…</p>}
        {pats.data?.length === 0 && <p className="meta">No tokens yet.</p>}
        <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {(pats.data ?? []).map((p) => (
            <li
              key={p.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 'var(--space-2)',
              }}
            >
              <span>
                <strong>{p.name}</strong>{' '}
                <span className="meta">
                  {p.revoked_at
                    ? '(revoked)'
                    : p.expires_at
                      ? `expires ${p.expires_at.slice(0, 10)}`
                      : 'no expiry'}
                  {p.last_used_at
                    ? ` · last used ${p.last_used_at.slice(0, 10)}`
                    : ' · never used'}
                </span>
              </span>
              {!p.revoked_at && (
                <Button
                  variant="ghost"
                  onClick={() => revokeMut.mutate(p.id)}
                  disabled={revokeMut.isPending}
                >
                  Revoke
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </main>
  )
}
