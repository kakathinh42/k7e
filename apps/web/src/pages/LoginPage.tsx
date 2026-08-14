/**
 * LoginPage — native email+password sign-in (with a register toggle) that posts
 * to the API and adopts the returned session. Renders callback error codes
 * (?error=…) instead of silently re-redirecting. Dev mode never routes here
 * (RequireAuth passes through).
 */

import { useState, type FormEvent } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import Alert from '../components/Alert'
import Button from '../components/Button'
import Card from '../components/Card'
import { useAuth } from '../auth/AuthContext'

export default function LoginPage() {
  const { mode, status, submitCredentials } = useAuth()
  const [params] = useSearchParams()
  const returnTo = params.get('returnTo') ?? '/'
  const error = params.get('error')
  const errorDetail = params.get('error_description')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isRegister, setIsRegister] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  if (mode === 'dev' || status === 'authenticated') {
    return <Navigate to={returnTo} replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setFormError(null)
    try {
      await submitCredentials(email.trim(), password, isRegister)
      // status flips to 'authenticated' → the guard above navigates on re-render
    } catch {
      setFormError(
        isRegister
          ? 'Registration failed — use your @example.com email and a password of at least 8 characters.'
          : 'Sign-in failed — check your email and password.',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="content stack" style={{ maxWidth: 420, margin: '10vh auto' }}>
      <Card>
        <div className="stack">
          <h1>
            <span className="dot" /> k7e
          </h1>
          <p className="meta">Sign in to see your team&apos;s knowledge base.</p>
          {error && (
            <Alert>
              Sign-in failed ({error}
              {errorDetail ? `: ${errorDetail}` : ''}). Try again or contact an
              administrator.
            </Alert>
          )}

          <form onSubmit={onSubmit} className="form-stack">
            {formError && <Alert>{formError}</Alert>}
            <div className="field">
              <label className="meta" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                className="input"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label className="meta" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                className="input"
                type="password"
                autoComplete={isRegister ? 'new-password' : 'current-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" variant="primary" disabled={loading}>
              {loading ? 'Please wait…' : isRegister ? 'Register' : 'Sign in'}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setIsRegister(!isRegister)
                setFormError(null)
              }}
            >
              {isRegister
                ? 'Have an account? Sign in'
                : 'New here? register with your email'}
            </Button>
          </form>
        </div>
      </Card>
    </main>
  )
}
